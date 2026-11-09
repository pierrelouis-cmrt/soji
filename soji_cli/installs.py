"""Installed-software trees and real development projects.

Shipped code of installed apps, editor extensions and tool runtimes looks like
project output (node_modules, dist, out, __pycache__), but no package manager
workflow restores it. These helpers answer two questions for the classifier:

* `InstallTrees.containing(path)`: is `path` strictly inside an install root?
  Rows there are never cleanup targets in any mode; only the install root as a
  whole can be (and only through its own rule).
* `InstallTrees.real_project(path)`: does the project owning `path` look like
  one the user works in (own lockfile and VCS root)? Project-dependency rules
  only match there.

Every answer depends on filesystem facts, so results share the catalog's
marker cache lifetime (cleared before each fresh verification).
"""
from __future__ import annotations
import json
import os
from pathlib import Path

# Groups whose matched folder is one installed unit: never split around nested
# hints, never descended for review, and every row inside one is refused.
ATOMIC_GROUPS = ('Toolchains and SDKs', 'Editor extensions')

# Rules that describe project output; they never match inside installed software.
DEV_GROUPS = ('Project dependencies', 'Build output')

# Home-relative install roots. Each match of a pattern is one install; anything
# below it is shipped code (including its out/, dist/, modules/, node_modules).
INSTALL_LOCATIONS = (
    '.vscode/extensions/*',
    '.vscode-insiders/extensions/*',
    '.vscode-oss/extensions/*',
    '.cursor/extensions/*',
    '.windsurf/extensions/*',
    '.antigravity/extensions/*',
    '.kiro/extensions/*',
    '.trae/extensions/*',
    '.positron/extensions/*',
    '.config/raycast/extensions/*',
    'Library/Application Support/com.raycast.macos/extensions/*',
    'Library/Application Support/Zed/extensions/*',
    # Squirrel/Electron apps (Discord, Slack, Teams...) keep each version here.
    'Library/Application Support/*/app-*',
    '.t3/tools/*',
    '.cache/codex-runtimes/*',
    '.codex/packages/*/releases/*',
    # Package-manager global prefixes contain installed executables/libraries.
    '.npm-global', '.local/lib/node_modules', '.local/lib/npm',
    'Library/pnpm', '.local/share/pnpm', '.bun/install/global',
    '.config/yarn/global', '.yarn/global', '.volta',
    # Version-manager installations (not their dedicated download caches).
    '.fnm/node-versions', '.local/share/fnm/node-versions',
    '.asdf/installs', '.local/share/mise/installs', '.deno/bin',
    # Plugin managers use lockfiles AND Git clones to install shipped code.
    '.local/share/nvim/lazy', '.local/share/nvim/site/pack',
    '.local/share/nvim/plugged', '.local/share/nvim/mason',
    '.vim/plugged', '.vim/pack', '.config/coc/extensions',
    '.local/share/JetBrains',
    'Library/Application Support/Sublime Text/Packages',
    'Library/Application Support/Sublime Text 3/Packages',
    'Library/Application Support/JetBrains/*/plugins',
)

# Home-relative areas where no development project lives: app-managed
# node_modules there (Zed's prettier, Electron app modules...) is installed code.
NO_PROJECT_AREAS = ('Library',)

LOCKFILES = (
    'package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb', 'bun.lock',
    'deno.lock', 'Podfile.lock', 'Cartfile.resolved', 'Gemfile.lock', 'composer.lock', 'poetry.lock',
    'uv.lock', 'Pipfile.lock', 'pdm.lock', 'pixi.lock', '.terraform.lock.hcl', 'Cargo.lock', 'go.sum',
    'mix.lock', 'pubspec.lock', 'packages.lock.json', 'gradle.lockfile', '*.opam.locked',
)
VCS_MARKERS = ('.git', '.hg', '.svn', '.jj', '.sl', '_darcs')
# Files that mark a folder as an installed extension/app package.
MANIFEST_FILES = ('extension.toml', '.vsixmanifest', 'extension.vsixmanifest')


def _ancestors(path: str, home: str, strict: bool = True):
    """All lexical ancestors of `path` below `home` (nearest first)."""
    p = Path(path)
    chain = list(p.parents) if strict else [p, *p.parents]
    out = []
    for parent in chain:
        s = str(parent)
        if s == home or not s.startswith(home.rstrip('/') + '/'):
            break
        out.append(s)
    return out


def package_manifest_kind(package_json: Path) -> str:
    """'VS Code extension', 'Raycast extension' or '' for a package.json."""
    try:
        if package_json.is_symlink() or package_json.stat().st_size > 2_000_000:
            return ''
        data = json.loads(package_json.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
        return ''
    if not isinstance(data, dict):
        return ''
    engines = data.get('engines')
    if isinstance(engines, dict) and 'vscode' in engines:
        return 'VS Code extension'
    if isinstance(data.get('publisher'), str) and data.get('publisher'):
        return 'VS Code extension'
    schema = data.get('$schema')
    commands = data.get('commands')
    if (isinstance(schema, str) and 'raycast' in schema.casefold()) or (
            isinstance(commands, list) and any(isinstance(c, dict) and 'mode' in c for c in commands)):
        return 'Raycast extension'
    return ''


class InstallTrees:
    def __init__(self, home: str, catalog):
        from .engine import glob_regex
        self.home = home.rstrip('/') or '/'
        self.catalog = catalog
        self.locations = [glob_regex(os.path.join(self.home, p)) for p in INSTALL_LOCATIONS]

    @property
    def cache(self):
        # Shares the marker cache, so it is cleared with it.
        return self.catalog.markers_cache

    def _vcs(self, folder: str) -> bool:
        """`folder` itself is a VCS root; ancestors never establish ownership."""
        return self.catalog.exists(Path(folder), list(VCS_MARKERS))

    def manifest(self, folder: str) -> str:
        """Kind of installed-package manifest in `folder`, or ''."""
        key = ('installs.manifest', folder)
        if key not in self.cache:
            kind = ''
            p = Path(folder)
            if folder.endswith('.app') or folder.endswith('.appex'):
                kind = 'application bundle'
            elif self.catalog.exists(p, list(MANIFEST_FILES)):
                kind = 'extension manifest'
            elif self.catalog.exists(p, ['package.json']):
                kind = package_manifest_kind(p / 'package.json')
            # A VCS checkout with a manifest is a project the user develops.
            if kind and kind != 'application bundle' and self._vcs(folder):
                kind = ''
            self.cache[key] = kind
        return self.cache[key]

    def root_kind(self, folder: str) -> str:
        """Why `folder` is an install root, or ''."""
        key = ('installs.root', folder)
        if key not in self.cache:
            reason = ''
            if any(rx.fullmatch(folder) for rx in self.locations):
                reason = 'installed app, extension or tool folder'
            else:
                match = self.catalog.match(folder)
                if match and match[0]['group'] in ATOMIC_GROUPS:
                    reason = match[0]['label']
                else:
                    reason = self.manifest(folder)
            self.cache[key] = reason
        return self.cache[key]

    def containing(self, path: str):
        """(install root, reason) for the outermost install root strictly
        containing `path`, or None."""
        path = path.rstrip('/') or '/'
        found = None
        for folder in _ancestors(path, self.home):
            reason = self.root_kind(folder)
            if reason:
                found = (folder, reason)
        return found

    def project_area(self, path: str) -> bool:
        """`path` may belong to a development project (not under ~/Library)."""
        return not any(path.startswith(os.path.join(self.home, area) + '/') for area in NO_PROJECT_AREAS)

    def real_project(self, path: str) -> bool:
        """The immediate owner has both a lockfile and its own VCS root."""
        # The immediate owner must carry its own lockfile AND VCS root.
        # A dotfiles checkout above it, or a global tool's lockfile, proves
        # nothing. Explicit install roots always take precedence.
        owner = str(Path(path).parent)
        return (not self.containing(path) and self.project_area(path)
                and self._vcs(owner)
                and self.catalog.exists(Path(owner), list(LOCKFILES)))
