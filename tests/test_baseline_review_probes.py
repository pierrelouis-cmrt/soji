"""Independent review probes for commit 21ce749 (November 8 fixes).

Each test asserts the SAFE expectation stated in the review brief. A failing
test therefore demonstrates a gap on the current code. Everything runs in a
disposable temporary fake home with a disposable Trash; externals are pinned
by tests/corpus.hermetic plus the FakeHome process/open-file injection.

Run:  python3 -m unittest discover -s review -v
"""
import json
import os
import plistlib
import stat
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))
from test_nov8_regressions import (FakeHome, write, age_tree, git, DAY, BLOB,  # noqa: E402
                                   RUNTIMES, ACTIVE, OLD, PRIMARY, DEPS)
from corpus import hermetic  # noqa: E402
from soji_cli import engine  # noqa: E402
from soji_cli.cleanup import Cleaner, create_plan, LIVE_USE_REASONS  # noqa: E402
from soji_cli.engine import MODES, Scanner  # noqa: E402


def runtime(version):
    return json.dumps({'bundleVersion': version, 'nodeVersion': '24'})


class Probe(FakeHome):
    def rel(self, f):
        return str(Path(f.path).relative_to(self.home))

    def picked(self, s, mode):
        return {self.rel(f) for f in self.selected(s, mode)}

    def picked_any_mode(self, s):
        return {m: sorted(self.picked(s, m)) for m in MODES}


# --------------------------------------------------------------------------
# Requirement 1: runtimes / toolchains
# --------------------------------------------------------------------------
class R1Runtime(Probe):
    def install(self, rel, version, age, payload=True):
        h = self.home
        write(h / rel / 'node-runtime.tar.xz', age=age)
        if version is not None:
            write(h / rel / 'payload/codex-primary-runtime/runtime.json', runtime(version), age)
        if payload:
            write(h / (rel + DEPS) / 'node/bin/node', age=age)
            write(h / (rel + DEPS) / 'python/bin/python3.12', age=age)
        age_tree(h / rel, age)

    def test_p1a_no_primary_lower_version_install_is_still_selected(self):
        """codex-primary-runtime missing: nothing positively identifies the
        runtime in use, yet the lower-version install is selected purely on
        'not the max version / not the newest'."""
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        s = self.scan()
        sel = self.picked_any_mode(s)
        for m in MODES:
            self.assertNotIn(OLD, sel[m], f'{m}: superseded only by max-version/newest, no positive proof')

    def test_p1b_complete_install_without_runtime_json_is_selected(self):
        """An install with a full payload (node/python binaries) but no
        runtime.json (metadata missing or layout changed) is treated as an
        'unfinished install' and removable."""
        self.install(OLD, None, 40, payload=True)
        self.install(ACTIVE, '26.1007.11041', 20)
        write(self.home / PRIMARY / 'runtime.json', runtime('26.1007.11041'), 3)
        s = self.scan()
        sel = self.picked_any_mode(s)
        for m in MODES:
            self.assertNotIn(OLD, sel[m], f'{m}: missing metadata is not proof of supersession')

    def test_p1c_incident_install_loses_protection_when_primary_version_install_arrives(self):
        """Opus' own fixture: primary is 26.1105 while the in-use L2Mqle is
        26.1007 (no primary match). L2Mqle is protected only as 'highest
        version'. A second install whose version equals the primary (e.g. a
        downloaded update not yet switched to) removes that protection."""
        write(self.home / PRIMARY / 'runtime.json', runtime('26.1105.12137'), 3)
        self.install(ACTIVE, '26.1007.11041', 29)
        self.install(RUNTIMES + '/codex-runtime-install-NEWxyz', '26.1105.12137', 8)
        s = self.scan()
        sel = self.picked_any_mode(s)
        rows = {self.rel(f): f for f in s.findings}
        for m in MODES:
            self.assertNotIn(ACTIVE, sel[m], m)

    def test_p1d_process_via_symlink_path_not_seen_as_running_inside(self):
        """ps comm reports the exec path as invoked (symlink not resolved).
        running_inside compares raw strings, so a program launched through a
        symlink to the install is not attributed to it (lsof would still
        list the real path when available)."""
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        link = self.home / '.local/bin/codex-node'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / (OLD + DEPS) / 'node/bin/node')
        self.processes = [str(link)]
        s = self.scan()
        rows = {self.rel(f): f for f in s.findings}
        self.assertTrue(any('running program' in h for h in rows[OLD].holds))

    def test_p1e_old_interior_plan_item_refused_at_fresh(self):
        """Positive check: an old-style plan item inside an install root
        (as in plan 0ea353e2) is refused by fresh verification now."""
        self.install(OLD, '26.901.1', 40)
        self.install(ACTIVE, '26.1007.11041', 20)
        state = self.home.parent / 'state'
        cleaner = Cleaner(state, trash_directory=self.home.parent / 'trash')
        s = self.scan()
        target = str(self.home / (ACTIVE + DEPS) / 'node/bin')
        from soji_cli.cleanup import file_identity
        n = s.nodes[target]
        f = s.classify(n)
        import dataclasses
        item = {'path': target, 'identity': file_identity(target), 'size': n.size, 'newest': n.newest,
                'files': n.files, 'hint': 'codex-runtimes', 'group': 'Toolchains and SDKs', 'action': {},
                'method': 'trash', 'finding': dataclasses.asdict(f)}
        plan = {'format': 'soji-clean-plan/1', 'id': 'x' * 32, 'createdAt': time.time(), 'mode': 'aggressive',
                'roots': [str(self.home)], 'home': str(self.home), 'protected': [], 'items': [item], 'method': 'trash',
                'warnings': []}
        from soji_cli.cleanup import digest
        plan['digest'] = digest(plan)
        with hermetic(str(self.home)):
            saved = engine.Scanner.collect_context
            engine.Scanner.collect_context = lambda sc: (setattr(sc, 'processes', []), setattr(sc, 'open_paths', []))
            try:
                result = cleaner.apply(plan)
            finally:
                engine.Scanner.collect_context = saved
        e = result['entries'][0]
        self.assertEqual(e['status'], 'failed')
        self.assertTrue(os.path.exists(target))


# --------------------------------------------------------------------------
# Requirement 2: shipped dependencies vs projects
# --------------------------------------------------------------------------
class R2Shipped(Probe):
    def pkg(self, folder, lock='package-lock.json', manifest=None, age=40):
        write(self.home / folder / 'package.json', json.dumps(manifest or {'name': 'x', 'version': '1.0.0'}), age)
        if lock:
            write(self.home / folder / lock, '{}', age)
        write(self.home / folder / 'node_modules/dep/index.js', age=age)
        write(self.home / folder / 'node_modules/dep/bin/tool', age=age)

    def check(self, folders, tag):
        age_tree(self.home, 40)
        s = self.scan()
        bad = []
        for m in MODES:
            for f in self.selected(s, m):
                if any(self.rel(f).startswith(x + '/') for x in folders):
                    bad.append((m, self.rel(f), f.hint_id, f.decision))
        self.assertFalse(bad)

    def test_p2a_global_package_manager_installs(self):
        """Global tool installs outside INSTALL_LOCATIONS: bun global (bun.lock),
        yarn v1 global (yarn.lock), mason.nvim npm packages (package-lock)."""
        self.pkg('.bun/install/global', lock='bun.lock')
        self.pkg('.config/yarn/global', lock='yarn.lock')
        self.pkg('.local/share/nvim/mason/packages/pyright', lock='package-lock.json')
        self.check(['.bun/install/global', '.config/yarn/global', '.local/share/nvim/mason/packages/pyright'], 'p2a')

    def test_p2b_dotfiles_vcs_ancestor_makes_shipped_deps_a_real_project(self):
        """~/.config tracked by a dotfiles Git repo (node_modules ignored):
        coc.nvim's extension store (package.json, no lockfile) becomes a
        'real project' through VCS ancestry."""
        cfg = self.home / '.config'
        write(cfg / 'nvim/init.lua', '-- x\n')
        write(cfg / '.gitignore', 'coc/\n')
        git(cfg, 'init', '-q', '-b', 'main'); git(cfg, 'add', '.'); git(cfg, 'commit', '-q', '-m', 'dotfiles')
        self.pkg('.config/coc/extensions', lock=None, manifest={'dependencies': {'coc-json': '>=0.0.0'}})
        self.check(['.config/coc/extensions'], 'p2b')

    def test_p2c_vcs_ancestor_cancels_manifest_install_exclusion(self):
        """A folder with a VS Code extension manifest is an install root, but
        a Git checkout anywhere above it (not just at it) cancels that."""
        tools = self.home / 'Tools'
        write(tools / 'README', 'x\n')
        write(tools / '.gitignore', 'ext-install/\n')
        git(tools, 'init', '-q', '-b', 'main'); git(tools, 'add', '.'); git(tools, 'commit', '-q', '-m', 'i')
        self.pkg('Tools/ext-install', manifest={'name': 'e', 'publisher': 'p', 'engines': {'vscode': '*'}})
        self.check(['Tools/ext-install'], 'p2c')

    def test_p2d_install_root_beyond_ancestor_depth_limit(self):
        """installs._ancestors stops after DEPTH=12 parents, so a nested
        node_modules deep inside an extension is no longer 'inside' it."""
        ext = '.vscode/extensions/pub.deep-1.0.0'
        write(self.home / ext / 'package.json', json.dumps({'publisher': 'pub', 'engines': {'vscode': '*'}}))
        deep = ext + '/dist/vendor/a/b/c/d/e/f/g/h/i/pkg'
        self.pkg(deep, lock='yarn.lock')
        self.check([ext], 'p2d')

    def test_p2e_positive_dedicated_caches_offered(self):
        """Positive: dedicated Electron/Chrome caches stay candidates (owner unknown -> held,
        so give the owner app and leave it not running)."""
        h = self.home
        for app, bundle in (('Code', 'com.microsoft.VSCode'), ('Google Chrome', 'com.google.Chrome')):
            (h / f'Applications/{app}.app/Contents').mkdir(parents=True)
            (h / f'Applications/{app}.app/Contents/Info.plist').write_bytes(
                plistlib.dumps({'CFBundleIdentifier': bundle, 'CFBundleName': app}))
        for rel in ('Library/Application Support/Code/Code Cache/js/a',
                    'Library/Application Support/Code/GPUCache/data_0',
                    'Library/Application Support/Code/CachedData/abc/x.code',
                    'Library/Application Support/Code/CachedExtensionVSIXs/ms-python.python-1',
                    'Library/Application Support/Google/GoogleUpdater/crx_cache/abc.crx'):
            write(h / rel)
        age_tree(h, 40)
        s = self.scan()
        sel = self.picked(s, 'balanced')
        rows = {self.rel(f): f for f in s.findings}
        for rel in ('Library/Application Support/Code/Code Cache', 'Library/Application Support/Code/GPUCache',
                    'Library/Application Support/Code/CachedExtensionVSIXs',
                    'Library/Application Support/Google/GoogleUpdater/crx_cache'):
            self.assertIn(rel, sel)
            self.assertFalse(rows[rel].holds)


# --------------------------------------------------------------------------
# Requirement 3: renamed project sessions
# --------------------------------------------------------------------------
class R3Sessions(Probe):
    def session(self, folder, cwd, name, hours):
        p = self.home / '.claude/projects' / folder / (name + '.jsonl')
        line = json.dumps({'type': 'user', 'cwd': str(cwd)}) + '\n'
        write(p, line.encode().ljust(BLOB, b' '), hours / 24)
        return p

    def gone_of(self, s, p):
        f = next(f for f in s.findings if f.path == str(p))
        moved = next((e for e in f.evidence if e.get('check') == 'sessionProjectMoved'), None)
        return f, moved

    def test_p3a_moved_to_other_parent_and_remote_renamed(self):
        """levo-terminal moved from ~/Documents/Github to ~/code and renamed
        soji, GitHub repo renamed too: same root commit, but no signal fires."""
        h = self.home
        new = h / 'code/soji'
        write(new / 'README.md', 'x\n', 0.2)
        git(new, 'init', '-q', '-b', 'main'); git(new, 'add', '.'); git(new, 'commit', '-q', '-m', 'init')
        git(new, 'remote', 'add', 'origin', 'https://github.com/me/soji.git')
        self.session('-Users-me-code-soji', new, 'now', 1)
        (h / 'Documents/Github').mkdir(parents=True)
        p = self.session('-Users-me-Documents-Github-levo-terminal', h / 'Documents/Github/levo-terminal', 'a', 30)
        s = self.scan()
        f, moved = self.gone_of(s, p)
        self.assertFalse(moved['gone'], 'renamed+moved project must not be judged gone')

    def test_p3b_non_git_project_renamed_in_place_without_new_activity(self):
        """A non-Git project renamed in the same parent, not yet opened by an
        agent under its new name: 'gone' and downgraded."""
        h = self.home
        write(h / 'projects/new-name/notes.md', 'x\n', 0.5)
        p = self.session('-Users-me-projects-old-name', h / 'projects/old-name', 'a', 30)
        s = self.scan()
        f, moved = self.gone_of(s, p)
        self.assertFalse(moved['gone'])

    def test_p3c_floor_on_sidecar_and_compound_rows(self):
        """24 h floor applies to compound sessions and sidecars too."""
        h = self.home
        (h / 'archive').mkdir()
        cwd = h / 'archive/deleted'
        p = self.session('-Users-me-archive-deleted', cwd, 's', 30)
        stem = p.with_suffix('')
        write(stem / 'subagents/agent-1.jsonl', b'x' * BLOB, 2 / 24)
        write(stem / 'tool-results/r.txt', b'x' * BLOB, 2 / 24)
        # orphan sidecar whose transcript is gone
        orphan = p.parent / 'orphan'
        write(orphan / 'subagents/agent-2.jsonl', b'x' * BLOB, 3 / 24)
        os.utime(h / 'archive', (time.time() - 100 * DAY,) * 2)
        s = self.scan()
        bad = []
        for f in s.findings:
            if '.claude/projects' in f.path:
                for m in ('careful', 'balanced'):
                    ok, why = f.decide(m, s.now)
                    newest = max([f.newest] + [x.get('newest', 0) for x in f.members])
                    if ok and s.now - newest < DAY:
                        bad.append((m, self.rel(f), f.hint_id, why))
        self.assertFalse(bad)


# --------------------------------------------------------------------------

class OwnershipProof(Probe):
    def test_global_and_plugin_roots_override_local_vcs_and_lockfiles(self):
        from soji_cli.installs import INSTALL_LOCATIONS
        roots = [p for p in INSTALL_LOCATIONS if '*' not in p]
        for root in roots:
            write(self.home / root / 'package-lock.json', '{}')
            (self.home / root / '.git').mkdir()
            write(self.home / root / 'node_modules/x/index.js')
        age_tree(self.home, 40)
        s = self.scan()
        for root in roots:
            self.assert_never_selected_inside(s, self.home / root)

    def test_parent_vcs_or_lockfile_alone_is_insufficient(self):
        (self.home / '.config/.git').mkdir(parents=True)
        for root in ('.config/tool', 'code/lock-only'):
            write(self.home / root / 'package-lock.json', '{}')
            write(self.home / root / 'node_modules/x/index.js')
        # An independently owned development root inside dotfiles is allowed.
        dev = self.home / '.config/myproj'
        write(dev / 'package-lock.json', '{}')
        write(dev / 'package.json', '{}')
        from test_nov8_regressions import git
        write(dev / '.gitignore', 'node_modules/\n')
        git(dev, 'init', '-q', '-b', 'main')
        git(dev, 'add', '.')
        git(dev, 'commit', '-q', '-m', 'fixture')
        write(dev / 'node_modules/x/index.js')
        age_tree(self.home, 40)
        s = self.scan()
        for root in ('.config/tool', 'code/lock-only'):
            self.assert_never_selected_inside(s, self.home / root)
        for mode in ('balanced', 'aggressive'):
            self.assertIn('.config/myproj/node_modules', self.picked(s, mode))

    def test_p2g_plugin_git_clone(self):
        from test_nov8_regressions import git
        plug = self.home / '.local/share/nvim/lazy/markdown-preview.nvim'
        write(plug / 'plugin/mkdp.vim', 'fixture')
        write(plug / '.gitignore', 'node_modules/\n')
        write(plug / 'app/package.json', '{"name":"mkdp"}')
        write(plug / 'app/yarn.lock', '')
        git(plug, 'init', '-q', '-b', 'main')
        git(plug, 'add', '.')
        git(plug, 'commit', '-q', '-m', 'fixture')
        write(plug / 'app/node_modules/x/index.js')
        age_tree(self.home, 40)
        self.assert_never_selected_inside(self.scan(), plug)
