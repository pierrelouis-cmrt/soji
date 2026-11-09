"""Launch-time version check.

Sōji asks GitHub for the latest release when it starts an interactive session
or a command that can delete. An outdated copy still scans, categorizes and
plans, but every cleanup is refused until it is updated: older rules and safety
checks should not move files that a newer release would treat differently.

If the check cannot complete (offline, GitHub unreachable, no release yet),
cleaning stays available and a note says the version could not be checked."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from . import __version__

REPO = os.environ.get('SOJI_REPO', 'pierrelouis-cmrt/soji')
CACHE_SECONDS = 15 * 60
TIMEOUT = 3.0

# Set once per process by enforce(); Cleaner.apply consults it.
_blocked: str | None = None


def parse_version(text):
    m = re.match(r'^v?(\d+(?:\.\d+)*)', str(text or '').strip())
    if not m:
        return None
    parts = [int(p) for p in m.group(1).split('.')]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def fetch_latest(timeout=TIMEOUT):
    url = os.environ.get('SOJI_UPDATE_URL') or f'https://api.github.com/repos/{REPO}/releases/latest'
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'soji-update-check'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(65536).decode('utf-8'))
    tag = data.get('tag_name') if isinstance(data, dict) else None
    if not parse_version(tag):
        raise ValueError('release has no version tag')
    return tag.lstrip('v')


def check(state_dir=None, *, timeout=TIMEOUT, fetch=fetch_latest, now=None):
    """{'status': 'current'|'outdated'|'unknown', 'current', 'latest', 'error'}"""
    now = time.time() if now is None else now
    cache = Path(state_dir).expanduser() / 'update-check.json' if state_dir else None
    latest = error = None
    try:
        cached = json.loads(cache.read_text()) if cache else None
        if (isinstance(cached, dict) and cached.get('current') == __version__
                and 0 <= now - float(cached.get('checkedAt', 0)) < CACHE_SECONDS
                and parse_version(cached.get('latest'))):
            latest = cached['latest']
    except (OSError, ValueError, TypeError):
        pass
    if latest is None:
        try:
            latest = fetch(timeout=timeout)
        except Exception as exc:  # network, HTTP, JSON: never fatal
            error = str(exc) or exc.__class__.__name__
        else:
            if cache:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({'checkedAt': now, 'current': __version__, 'latest': latest}))
                except OSError:
                    pass
    if latest is None:
        return {'status': 'unknown', 'current': __version__, 'latest': None, 'error': error}
    outdated = parse_version(latest) > parse_version(__version__)
    return {'status': 'outdated' if outdated else 'current', 'current': __version__, 'latest': latest, 'error': None}


def install_kind():
    """How this copy was installed: 'brew', 'script', 'git' or None."""
    here = Path(__file__).resolve()
    text = str(here)
    if '/Cellar/soji/' in text:
        return 'brew'
    if '.pyz' in text and '/share/soji/' in text:
        return 'script'
    root = here.parent.parent
    if (root / '.git').exists() and (root / 'entrypoint.py').exists():
        return 'git'
    return None


def upgrade_command(kind=None):
    kind = kind or install_kind()
    if kind == 'brew':
        return ['brew', 'upgrade', 'soji']
    if kind == 'script':
        return ['/bin/sh', '-c', f'curl -fsSL https://raw.githubusercontent.com/{REPO}/main/install.sh | sh']
    if kind == 'git':
        return ['git', '-C', str(Path(__file__).resolve().parent.parent), 'pull', '--ff-only']
    return None


def upgrade_hint(kind=None):
    command = upgrade_command(kind)
    if command is None:
        return f'download the latest release from https://github.com/{REPO}/releases'
    return command[-1] if command[0] == '/bin/sh' else ' '.join(command)


def blocked_reason():
    return _blocked


def block(reason):
    global _blocked
    _blocked = reason


def ensure_cleaning_allowed():
    if _blocked:
        raise ValueError(_blocked)


def outdated_reason(result):
    return (f"Sōji {result['latest']} is available (this is {result['current']}). "
            f"Cleaning is disabled until you update: {upgrade_hint()}. Scanning and planning still work.")


def enforce(state_dir):
    """Check once; block cleanup for the rest of the process when outdated."""
    result = check(state_dir)
    if result['status'] == 'outdated':
        block(outdated_reason(result))
    return result


def relaunch():
    """Start the updated copy with the same arguments (never returns on success)."""
    os.environ['SOJI_RELAUNCHED'] = __version__
    kind = install_kind()
    args = sys.argv[1:]
    if kind in ('brew', 'script'):
        command = shutil.which('soji')
        if command:
            os.execv(command, [command, *args])
    os.execv(sys.executable, [sys.executable, sys.argv[0], *args])


def interactive_gate(state_dir, ask=input, out=sys.stderr, run=subprocess.run):
    """Before the TUI: check, offer to update, otherwise continue in scan-only mode."""
    result = enforce(state_dir)
    if result['status'] == 'unknown':
        print(f"Sōji {result['current']}: could not check for updates ({result['error']}).", file=out)
        return result
    if result['status'] != 'outdated':
        return result
    print(f"\nSōji {result['latest']} is available. You have {result['current']}.", file=out)
    print('An outdated copy can scan and categorize, but cleaning is turned off until you update.', file=out)
    command = upgrade_command()
    if command is None or os.environ.get('SOJI_RELAUNCHED'):
        print(f'Update with: {upgrade_hint()}', file=out)
        try:
            ask('Press Return to continue in scan-only mode… ')
        except EOFError:
            pass
        return result
    try:
        answer = ask(f'Update now ({upgrade_hint()})? [Y/n] ').strip().lower()
    except EOFError:
        answer = 'n'
    if answer in ('', 'y', 'yes'):
        try:
            done = run(command).returncode == 0
        except OSError as exc:
            print(f'Update failed: {exc}', file=out)
            done = False
        if done:
            print('Updated. Restarting Sōji…', file=out)
            relaunch()
        print('Update did not complete; continuing in scan-only mode.', file=out)
    else:
        print('Continuing in scan-only mode.', file=out)
    return result
