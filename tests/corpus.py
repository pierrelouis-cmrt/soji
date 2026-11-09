"""Synthetic regression corpus and hermetic scan harness.

The corpus is a small fake home directory with known ages, version families,
present/missing workspaces, Git states, simulator devices and agent activity.
`scan_corpus` scans it with every machine-dependent input pinned (processes,
open files, installed apps, simctl/devicectl, native helper) and returns one
normalized row per finding with the decision for each cleanup mode.

The rows are the comparison unit: two exports (for example before and after
a change) are diffed with `diff_rows`. Ages are whole days so second-level drift between
building and scanning never changes a decision.
"""
from __future__ import annotations

import contextlib
import json
import os
import plistlib
import subprocess
import time
from pathlib import Path

MODES = ('careful', 'balanced', 'aggressive')
DAY = 86400
PAYLOAD = 128 * 1024          # one candidate payload file, a 4 KiB multiple
MIN_BYTES = 64 * 1024         # hides marker files; every payload stays visible
DEFAULT_AGE = 400             # days, for anything not declared below

BOOTED = '11111111-1111-1111-1111-111111111111'
SPARE = '22222222-2222-2222-2222-222222222222'
PEER = '33333333-3333-3333-3333-333333333333'
ORPHAN = '44444444-4444-4444-4444-444444444444'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-18-0'

SIMCTL = {
    'devices': {RUNTIME: [
        {'udid': BOOTED, 'state': 'Booted', 'isAvailable': True, 'name': 'Booted phone'},
        # SPARE and PEER are twins (same name and runtime); only PEER has an app.
        {'udid': SPARE, 'state': 'Shutdown', 'isAvailable': True, 'name': 'iPhone 16'},
        {'udid': PEER, 'state': 'Shutdown', 'isAvailable': True, 'name': 'iPhone 16'},
    ]},
    'runtimes': [{'identifier': RUNTIME, 'isAvailable': True}],
}

# (home-relative path, payload bytes or None for a directory marker, age days)
# A declared path's age applies to it and every undeclared descendant.
LAYOUT: list[tuple[str, int | None, float]] = [
    # Node projects: idle, recently edited, dirty Git, clean Git, secrets.
    ('code/old-web', None, 40), ('code/old-web/package.json', 64, 40), ('code/old-web/package-lock.json', 64, 40),
    ('code/old-web/node_modules/lib/index.js', PAYLOAD, 40),
    ('code/fresh-web', None, 30), ('code/fresh-web/package.json', 64, 1), ('code/fresh-web/pnpm-lock.yaml', 64, 30),
    ('code/fresh-web/node_modules/lib/index.js', PAYLOAD, 30),
    ('code/dirty-web', None, 60), ('code/dirty-web/package.json', 64, 60),
    ('code/dirty-web/notes.txt', 64, 60),
    ('code/dirty-web/node_modules/lib/index.js', PAYLOAD, 60),
    ('code/clean-web', None, 60), ('code/clean-web/package.json', 64, 60),
    ('code/clean-web/assets.bin', PAYLOAD, 60),
    ('code/clean-web/node_modules/lib/index.js', PAYLOAD, 60),
    ('code/secret-web', None, 60), ('code/secret-web/package.json', 64, 60), ('code/secret-web/yarn.lock', 64, 60),
    ('code/secret-web/node_modules/lib/index.js', PAYLOAD, 60),
    ('code/secret-web/node_modules/lib/.env', 64, 60),
    # Rust target with marker, and an unrelated `target` without one.
    ('code/rusty', None, 20), ('code/rusty/Cargo.toml', 64, 20),
    ('code/rusty/target/debug/app', PAYLOAD, 20),
    ('code/unrelated/target/blob', PAYLOAD, 90),
    # Python venvs: idle project versus one an agent session touched recently.
    ('code/py-idle', None, 45), ('code/py-idle/pyproject.toml', 64, 45), ('code/py-idle/uv.lock', 64, 45),
    ('code/py-idle/.venv/pyvenv.cfg', 64, 45),
    ('code/py-idle/.venv/lib/site.py', PAYLOAD, 45),
    ('code/py-agent', None, 45), ('code/py-agent/pyproject.toml', 64, 45), ('code/py-agent/poetry.lock', 64, 45),
    ('code/py-agent/.venv/pyvenv.cfg', 64, 45),
    ('code/py-agent/.venv/lib/site.py', PAYLOAD, 45),
    # App caches: owned by an installed app, unowned, fresh, tool-owned.
    ('Applications/Known.app/Contents/MacOS/Known', 64, 100),
    ('Library/Caches/com.example.Known/blob', PAYLOAD, 10),
    ('Library/Caches/com.example.Unknown/blob', PAYLOAD, 10),
    ('Library/Caches/com.example.Fresh/blob', PAYLOAD, 0.001),
    ('Library/Caches/pip/http/blob', PAYLOAD, 10),
    # Specific hints nested under the generic ~/Library/Caches/* hint.
    ('Library/Caches/Homebrew/downloads/bottle.tar.gz', PAYLOAD, 10),
    ('Library/Caches/Homebrew/bootsnap/blob', PAYLOAD, 10),
    ('Library/Caches/JetBrains/IntelliJIdea2025.1/caches/blob', PAYLOAD, 10),
    ('Library/Caches/JetBrains/IntelliJIdea2025.1/log/blob', PAYLOAD, 10),
    # Xcode DerivedData with present/missing workspaces.
    ('Library/Developer/Xcode/DerivedData/Present-abc/Build/blob', PAYLOAD, 20),
    ('Library/Developer/Xcode/DerivedData/Missing-def/Build/blob', PAYLOAD, 20),
    ('Library/Developer/Xcode/DerivedData/Recent-ghi/Build/blob', PAYLOAD, 3),
    # Version families: nvm (active alias + age rule), playwright (by product).
    # v16.0.0 is pinned only through an nvm alias named in a project .nvmrc.
    ('.nvm/versions/node/v16.0.0/bin/node', PAYLOAD, 120),
    ('code/pinned-web', None, 50),
    ('.nvm/versions/node/v18.0.0/bin/node', PAYLOAD, 100),
    ('.nvm/versions/node/v20.1.0/bin/node', PAYLOAD, 60),
    ('.nvm/versions/node/v22.3.0/bin/node', PAYLOAD, 40),
    ('Library/Caches/ms-playwright/chromium-1100/chrome', PAYLOAD, 90),
    ('Library/Caches/ms-playwright/chromium-1200/chrome', PAYLOAD, 30),
    ('Library/Caches/ms-playwright/firefox-1400/firefox', PAYLOAD, 60),
    # Simulators: booted, spare shut-down, peer with apps, orphan.
    (f'Library/Developer/CoreSimulator/Devices/{BOOTED}/data/blob', PAYLOAD, 30),
    (f'Library/Developer/CoreSimulator/Devices/{SPARE}/data/blob', PAYLOAD, 30),
    (f'Library/Developer/CoreSimulator/Devices/{PEER}/data/blob', PAYLOAD, 30),
    (f'Library/Developer/CoreSimulator/Devices/{PEER}/data/Containers/Bundle/Application/App/x', 64, 30),
    (f'Library/Developer/CoreSimulator/Devices/{ORPHAN}/data/blob', PAYLOAD, 30),
    # Device support with no connected-device information.
    ('Library/Developer/Xcode/iOS DeviceSupport/iPhone15,2 17.0 (21A329)/Symbols/blob', PAYLOAD, 90),
    ('Library/Developer/Xcode/iOS DeviceSupport/iPhone15,2 18.0 (22A3354)/Symbols/blob', PAYLOAD, 20),
    # Downloads, Trash, sessions, personal files.
    ('Downloads/old-installer.dmg', PAYLOAD, 45),
    ('Downloads/new-installer.dmg', PAYLOAD, 3),
    ('Downloads/photos.zip', PAYLOAD, 60),
    ('Downloads/movie.part', PAYLOAD, 10),
    ('.Trash/junk.bin', PAYLOAD, 10),
    ('.claude/projects/-code-py-agent/session.jsonl', PAYLOAD, 2),
    ('Documents/report.pdf', PAYLOAD, 100),
    # November 8 regressions. A folder with only package.json is no project.
    ('code/loose-web', None, 60), ('code/loose-web/package.json', 64, 60),
    ('code/loose-web/node_modules/lib/index.js', PAYLOAD, 60),
    # Shipped node_modules of installed extensions/apps, with lockfiles.
    *[(f'{root}/{rel}', size, 254) for root in (
        '.vscode/extensions/ritwickdey.liveserver-5.7.10',
        '.config/raycast/extensions/112ad714-bf10-4ccc-a70f-4232bb2241a5',
        'Library/Application Support/Zed/extensions/work/html',
        'Library/Application Support/discord/app-0.0.411/modules/discord_spellcheck-1/discord_spellcheck',
        '.t3/tools/expo-device-hub/0.15.3',
    ) for rel, size in (('package.json', 64), ('package-lock.json', 64), ('node_modules/lib/index.js', PAYLOAD))],
    ('.vscode/extensions/ms-python.python-2026.10.0-darwin-arm64/out/client/node_modules/lib/index.js', PAYLOAD, 21),
    ('.vscode/extensions/ms-python.python-2026.10.0-darwin-arm64/out/client/package.json', 64, 21),
    # Codex runtimes: the install in use (fresh __pycache__) and a superseded one.
    ('.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node', PAYLOAD, 3),
    ('.cache/codex-runtimes/codex-runtime-install-L2Mqle/node-runtime.tar.xz', PAYLOAD, 29),
    ('.cache/codex-runtimes/codex-runtime-install-L2Mqle/payload/codex-primary-runtime/dependencies/node/node_modules/pdfjs-dist/pdf.mjs', PAYLOAD, 29),
    ('.cache/codex-runtimes/codex-runtime-install-L2Mqle/payload/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages/pandas/__pycache__/core.pyc', PAYLOAD, 0.001),
    ('.cache/codex-runtimes/codex-runtime-install-wDayCH/node-runtime.tar.xz', PAYLOAD, 40),
    # Global and plugin installs carry lockfiles/VCS too; never project output.
    *[(f'{root}/{rel}', size, 60) for root in (
        '.bun/install/global', '.config/yarn/global',
        '.local/share/nvim/mason/packages/pyright',
        '.local/share/nvim/lazy/markdown-preview.nvim/app',
        '.config/coc/extensions',
    ) for rel, size in (('package.json', 64), ('package-lock.json', 64), ('node_modules/lib/index.js', PAYLOAD))],
    # Sessions of a renamed project (code/old-name -> code/new-name).
    ('code/new-name/README.md', 64, 1),
    ('.claude/projects/-code-old-name/renamed.jsonl', PAYLOAD, 1.5),
    ('.claude/projects/-code-new-name/current.jsonl', PAYLOAD, 0.5),
]


def _age_for(rel: str, ages: dict[str, float]) -> float:
    probe = rel
    while True:
        if probe in ages:
            return ages[probe]
        if '/' not in probe:
            return DEFAULT_AGE
        probe = probe.rsplit('/', 1)[0]


def _git(repo: Path, *args: str) -> None:
    env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='corpus', GIT_AUTHOR_EMAIL='corpus@example.invalid',
               GIT_COMMITTER_NAME='corpus', GIT_COMMITTER_EMAIL='corpus@example.invalid')
    subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                    '-C', str(repo), *args], check=True,
                   capture_output=True, env=env)


def build_corpus(home: Path, now: float | None = None) -> float:
    """Create the corpus under `home`; return the reference time used."""
    now = time.time() if now is None else now
    home = Path(home)
    ages = {rel: age for rel, _, age in LAYOUT}
    for rel, size, _ in LAYOUT:
        p = home / rel
        if size is None:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * size)
    for session, cwd in [('-code-py-agent/session.jsonl', 'code/py-agent'),
                         ('-code-old-name/renamed.jsonl', 'code/old-name'),
                         ('-code-new-name/current.jsonl', 'code/new-name')]:
        line = json.dumps({'type': 'user', 'cwd': str(home / cwd)}) + '\n'
        (home / '.claude/projects' / session).write_bytes(line.encode().ljust(PAYLOAD, b' '))
    for runtime, version in [('codex-primary-runtime', '26.1105.12137'),
                             ('codex-runtime-install-L2Mqle/payload/codex-primary-runtime', '26.1007.11041')]:
        (home / '.cache/codex-runtimes' / runtime / 'runtime.json').write_text(json.dumps({'bundleVersion': version}))
    ext = home / '.vscode/extensions/ritwickdey.liveserver-5.7.10/package.json'
    ext.write_text(json.dumps({'name': 'LiveServer', 'publisher': 'ritwickdey', 'engines': {'vscode': '^1.22.0'}}))
    # device.plist as CoreSimulator writes it (state 1 = Shutdown, 3 = Booted).
    for d in SIMCTL['devices'][RUNTIME]:
        info = {'UDID': d['udid'], 'name': d['name'], 'runtime': RUNTIME, 'state': 3 if d['state'] == 'Booted' else 1}
        (home / 'Library/Developer/CoreSimulator/Devices' / d['udid'] / 'device.plist').write_bytes(plistlib.dumps(info))
    plist = {'CFBundleIdentifier': 'com.example.Known', 'CFBundleName': 'Known'}
    (home / 'Applications/Known.app/Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    dd = home / 'Library/Developer/Xcode/DerivedData'
    for name, workspace in [('Present-abc', home / 'code/old-web'), ('Missing-def', home / 'code/gone'),
                            ('Recent-ghi', home / 'code/gone')]:
        (dd / name / 'info.plist').write_bytes(plistlib.dumps({'WorkspacePath': str(workspace)}))
    # nvm aliases as nvm writes them: default -> lts/* -> lts/iron -> v20.1.0,
    # and a project pin naming another LTS alias (lts/gallium -> v16.0.0).
    (home / '.nvm/alias/lts').mkdir(parents=True, exist_ok=True)
    (home / '.nvm/alias/default').write_text('lts/*\n')
    (home / '.nvm/alias/lts/*').write_text('lts/iron\n')
    (home / '.nvm/alias/lts/iron').write_text('v20.1.0\n')
    (home / '.nvm/alias/lts/gallium').write_text('v16.0.0\n')
    (home / 'code/pinned-web/.nvmrc').write_text('lts/gallium\n')
    for repo in ('code/dirty-web', 'code/clean-web', 'code/old-web', 'code/fresh-web',
                 'code/secret-web', 'code/py-idle', 'code/py-agent'):
        r = home / repo
        if repo in ('code/dirty-web', 'code/clean-web'):
            (r / 'package-lock.json').write_text('{}')
        (r / '.gitignore').write_text('node_modules/\n.claude/\n')
        _git(r, 'init', '-q', '-b', 'main')
        _git(r, 'add', '.')
        _git(r, 'commit', '-q', '-m', 'init')
    (home / 'code/dirty-web/wip.txt').write_text('untracked work\n')
    # Merged but never pushed: the worktree hold must come from push state.
    _git(home / 'code/clean-web', 'worktree', 'add', '-q', '-b', 'feature', '.claude/worktrees/feature')
    ages['code/clean-web/.claude/worktrees/feature'] = 10
    # Merged and pushed (local bare remote beside the fake home) Codex
    # worktrees: one holds only regenerable ignored output, the other a unique
    # ignored database that `git worktree remove` would delete.
    app = home / 'code/agent-app'
    app.mkdir(parents=True, exist_ok=True)
    (app / 'README.md').write_text('agent app\n')
    (app / '.gitignore').write_text('node_modules/\nlocal-data/\n*.sqlite\n')
    _git(app, 'init', '-q', '-b', 'main')
    _git(app, 'add', '.')
    _git(app, 'commit', '-q', '-m', 'init')
    remote = home.parent / 'corpus-agent-app.git'
    _git(home.parent, 'init', '-q', '--bare', str(remote))
    _git(app, 'remote', 'add', 'origin', str(remote))
    _git(app, 'push', '-q', '-u', 'origin', 'main')
    for name, rel in [('safe', 'node_modules/lib/index.js'), ('data', 'local-data/notes.sqlite')]:
        _git(app, 'worktree', 'add', '-q', '--detach', str(home / '.codex/worktrees' / name))
        payload = home / '.codex/worktrees' / name / rel
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(b'x' * PAYLOAD)
        ages['.codex/worktrees/' + name] = 30
    ages['code/agent-app'] = 30
    # Ages last, children before parents, so directory mtimes stick.
    for folder, dirs, files in os.walk(home, topdown=False):
        for name in [*files, *dirs, None]:
            p = Path(folder) if name is None else Path(folder, name)
            if p == home:
                continue
            stamp = now - _age_for(str(p.relative_to(home)), ages) * DAY
            os.utime(p, (stamp, stamp), follow_symlinks=False)
    return now


@contextlib.contextmanager
def hermetic(home: str | None = None):
    """Pin every machine-dependent scan input; Git still runs on the corpus.

    With `home`, Git discovery stops at its parent so fixture projects never
    resolve to an enclosing repository (such as this one).
    """
    from soji_cli import apps, catalogs, engine, platform, specialized, gitstate
    unavailable = {'error': 'Native helper disabled for corpus scan'}
    real_git_env = gitstate.git_env

    def fixture_git_env():
        # Production strips inherited GIT_*; explicitly keep fixture discovery
        # inside this fake home, including when the corpus lives in a checkout.
        env = real_git_env()
        if home:env['GIT_CEILING_DIRECTORIES'] = str(Path(home).parent)
        return env

    def native(operation, *args, **kw):
        return [] if operation=='apps' else unavailable

    def json_command(argv, timeout=8):
        argv = [str(a) for a in argv]
        return json.loads(json.dumps(SIMCTL)) if argv[1:4] == ['simctl', 'list', '--json'] else None

    def command(argv, timeout=8, env=None):
        return -1, '', 'disabled for corpus scan'

    def collect_context(self):
        self.processes = []
        self.open_paths = []

    patches = [
        (gitstate, 'git_env', fixture_git_env),
        (engine.Scanner, 'collect_context', collect_context),
        (platform, 'native', native), (apps, 'native', native), (catalogs, 'native', native),
        (specialized, 'json_command', json_command), (catalogs, 'json_command', json_command),
        (specialized, 'command', command), (catalogs, 'command', command),
        (apps.AppCatalog, 'SYSTEM_ROOTS', ()), (apps.InstalledTools, 'SYSTEM_AGENT_ROOTS', ()),
    ]
    saved = [(obj, name, obj.__dict__[name]) for obj, name, _ in patches]
    saved_env = {k: os.environ.pop(k) for k in ('CODEX_HOME', 'GIT_CEILING_DIRECTORIES') if k in os.environ}
    if home:
        os.environ['GIT_CEILING_DIRECTORIES'] = str(Path(home).parent)
    try:
        for obj, name, value in patches:
            setattr(obj, name, value)
        yield
    finally:
        for obj, name, value in saved:
            setattr(obj, name, value)
        os.environ.pop('GIT_CEILING_DIRECTORIES', None)
        os.environ.update(saved_env)


def _clean(text: str, home: str) -> str:
    return text.replace(home, '~')


def normalize(report_findings: list[dict], home: str, mode: str) -> dict[str, dict]:
    """Reduce one mode's findings to comparable rows keyed by `~/path`."""
    rows = {}
    for f in report_findings:
        retention = next((e for e in f.get('evidence', []) if e.get('check') == 'retention'), None)
        rows[_clean(f['path'], home)] = {
            'hint': f.get('hint_id') or None,
            'group': f['group'],
            'bytes': f['size'],
            'rank': retention['rank'] if retention else None,
            'holds': sorted({_clean(h, home) for h in f.get('holds', [])}),
            'modeHolds': {m: _clean(v, home) for m, v in sorted(f.get('mode_holds', {}).items())},
            'early': f.get('rule_early_reason'),
            'action': (f.get('action') or {}).get('kind'),
            mode: {'selected': f['selected'], 'decision': _clean(f['decision'], home)},
        }
    return rows


def scan_corpus(home: Path) -> list[dict]:
    """Scan a built corpus hermetically; return rows sorted by path."""
    from soji_cli.engine import Scanner
    home_s = os.path.realpath(home)
    merged: dict[str, dict] = {}
    with hermetic(home_s):
        scanner = Scanner([home_s], home=home_s, min_bytes=MIN_BYTES, context=True)
        scanner.run()
        if scanner.error:
            raise RuntimeError(scanner.error)
        for mode in MODES:
            for path, row in normalize(scanner.report(mode)['findings'], home_s, mode).items():
                merged.setdefault(path, {}).update(row)
    return [{'path': p, **merged[p]} for p in sorted(merged)]


def diff_rows(expected: list[dict], actual: list[dict]) -> list[str]:
    """Human-readable field-level differences between two row sets."""
    a = {r['path']: r for r in expected}
    b = {r['path']: r for r in actual}
    out = []
    for path in sorted(a.keys() | b.keys()):
        if path not in b:
            out.append(f'- {path}: missing')
            continue
        if path not in a:
            out.append(f'+ {path}: new row {json.dumps(b[path], sort_keys=True)}')
            continue
        for key in sorted(a[path].keys() | b[path].keys()):
            if a[path].get(key) != b[path].get(key):
                out.append(f'~ {path} [{key}]: {json.dumps(a[path].get(key))} -> {json.dumps(b[path].get(key))}')
    return out

