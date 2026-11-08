"""Native bulk walk: the same nodes as `Scanner.visit`, measured by the helper.

`soji-native walk` reads directories with getattrlistbulk on parallel workers,
re-reads ambiguous entries with fstatat, then aggregates sequentially in readdir
order (hardlink shares and first-name logical bytes included). The result is
decoded here into `Node` rows identical to a Python walk. Python's `visit`
stays the reference implementation and the fallback: it is used when the helper
is missing, when SOJI_NATIVE_WALK=0, when `visit` is patched, and for every
cleanup re-verification.
"""
from __future__ import annotations

from array import array
import json
import os
import signal
import subprocess
import threading

from .engine import (CLOUD_NAMES, PRIVATE_HOME, PRIVATE_NAMES, PRIVATE_SUFFIXES,
                     SECRET_SUFFIXES, Node)

# Index = reason code emitted by the helper (Reason in SojiNative.swift).
REASONS = (
    '',
    'Scan stopped before measuring',
    'Unreadable entry',
    'Symlink; not followed',
    'Mount boundary or depth limit; contents not scanned',
    'User protected path',
    'Credentials or repository metadata; contents not scanned',
    'Personal library; contents not scanned',
    'Private or cloud data; contents not scanned',
    'Cloud-synced folder; contents not scanned',
    'Agent memory; contents not scanned',
    'Installed application bundle; contents not scanned',
)
SECRET_NAMES = ('credentials.json', 'id_rsa', 'id_ed25519')
MAX_DEPTH = 128
# (typecode, field) in the helper's column order.
COLUMNS = (('i', 'parent'), ('q', 'size'), ('q', 'apparent'), ('q', 'files'),
           ('d', 'newest'), ('d', 'own_newest'), ('q', 'errors'), ('i', 'own_errors'),
           ('B', 'flags'), ('B', 'reason'), ('q', 'device'), ('Q', 'inode'),
           ('q', 'own_size'), ('q', 'own_apparent'), ('i', 'link_count'))


def helper():
    """Path of the bundled helper, or None (no helper, or disabled)."""
    if os.environ.get('SOJI_NATIVE_WALK', '1') == '0':
        return None
    override = os.environ.get('SOJI_NATIVE_WALK_HELPER')
    if override:
        return override if os.path.isfile(override) else None
    return _bundled()


_extracted = []


def _bundled():
    """The packaged helper; inside a zipapp it is extracted once per process."""
    try:
        from importlib.resources import files, as_file
        resource = files('soji_cli').joinpath('native-bin', 'soji-native')
        if not resource.is_file():
            return None
        path = str(resource)
        if os.path.isfile(path):
            return path
        if not _extracted:
            import atexit
            context = as_file(resource)
            extracted = str(context.__enter__())
            atexit.register(context.__exit__, None, None, None)
            os.chmod(extracted, 0o700)
            _extracted.append(extracted)
        return _extracted[0]
    except (OSError, TypeError, ValueError):
        return None


def available(scanner) -> bool:
    from .engine import Scanner
    # A patched or overridden visit (tests, benchmarks) keeps the Python walk.
    if 'visit' in vars(scanner) or type(scanner).visit is not Scanner.visit:
        return False
    if type(scanner).private is not Scanner.private:
        return False
    return helper() is not None


def config(scanner, roots, max_seconds):
    private_home = [os.path.join(scanner.home, r) for r in PRIVATE_HOME]
    return {
        'roots': [{'path': p, 'depth': d, 'device': dev, 'stopNode': stop} for p, d, dev, stop in roots],
        'protected': list(scanner.protected), 'privateHome': private_home,
        'privateNames': sorted(PRIVATE_NAMES), 'privateSuffixes': list(PRIVATE_SUFFIXES),
        'cloudNames': list(CLOUD_NAMES), 'secretPrefixes': ['.env'],
        'secretSuffixes': list(SECRET_SUFFIXES), 'secretNames': list(SECRET_NAMES),
        'maxFiles': max(0, scanner.max_files - scanner.visited), 'maxSeconds': max_seconds,
        'maxDepth': MAX_DEPTH, 'threads': threads(),
        'forceStat': os.environ.get('SOJI_NATIVE_WALK_STAT') == '1',
    }


def threads():
    try:
        value = int(os.environ.get('SOJI_NATIVE_WALK_THREADS', '0'))
    except ValueError:
        value = 0
    return value if value > 0 else min(8, os.cpu_count() or 4)


def walk(scanner, roots):
    """Measure roots [(path, depth, device, stop_node)] into scanner.nodes.

    Returns False (nothing changed) when the helper cannot be run, so the
    caller falls back to `visit`. Counters, limits and progress are updated
    the same way `visit` updates them.
    """
    binary = helper()
    if binary is None:
        return False
    import time
    remaining = scanner.max_seconds - (time.monotonic() - scanner.started)
    if scanner.cancel.is_set():
        remaining = -1
    request = json.dumps(config(scanner, roots, remaining)).encode()
    try:
        proc = subprocess.Popen([binary, 'walk'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except OSError:
        return False
    base_visited = scanner.visited

    def progress():
        for raw in proc.stderr:
            count, _, path = raw.decode('utf-8', 'surrogateescape').rstrip('\n').partition('\t')
            if count.isdigit():
                scanner.visited = base_visited + int(count)
                scanner.current = path
                scanner.set_progress('scan', scanner.visited, path=path)

    def cancel_watch():
        while proc.poll() is None:
            if scanner.cancel.wait(0.1):
                try:
                    proc.send_signal(signal.SIGTERM)
                except OSError:
                    pass
                return

    reader = threading.Thread(target=progress, daemon=True)
    watcher = threading.Thread(target=cancel_watch, daemon=True)
    reader.start()
    watcher.start()
    try:
        try:
            proc.stdin.write(request)
            proc.stdin.close()
            payload = proc.stdout.read()
        except OSError:
            proc.kill()
            proc.wait()
            return False
        code = proc.wait()
        reader.join(1)
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
    scanner.visited = base_visited
    if code != 0:
        return False
    try:
        decode(scanner, payload)
    except (ValueError, IndexError, KeyError, UnicodeError):
        return False
    return True


def decode(scanner, payload):
    newline = payload.index(b'\n')
    header = json.loads(payload[:newline])
    count = header['count']
    offset = newline + 1
    columns = {}
    for code, field in COLUMNS:
        column = array(code)
        size = column.itemsize * count
        column.frombytes(payload[offset:offset + size])
        if len(column) != count:
            raise ValueError('Truncated native walk')
        columns[field] = column.tolist()
        offset += size
    names_blob = payload[offset:offset + header['namesBytes']]
    if len(names_blob) != header['namesBytes']:
        raise ValueError('Truncated native walk')
    names = names_blob.decode('utf-8', 'surrogateescape').split('\0') if count else []
    if len(names) != count:
        raise ValueError('Native walk name count mismatch')
    c = columns
    parent, flags, reason = c['parent'], c['flags'], c['reason']
    size, apparent, files = c['size'], c['apparent'], c['files']
    newest, own_newest, errors, own_errors = c['newest'], c['own_newest'], c['errors'], c['own_errors']
    device, inode, own_size, own_apparent, link_count = (
        c['device'], c['inode'], c['own_size'], c['own_apparent'], c['link_count'])
    nodes = scanner.nodes
    inodes = scanner._inodes
    paths = [None] * count
    made = [None] * count
    reasons = REASONS
    for i in range(count):
        p = parent[i]
        if p < 0:
            path = names[i]
        else:
            base = paths[p]
            path = base + names[i] if base.endswith('/') else base + '/' + names[i]
        paths[i] = path
        f = flags[i]
        node = Node(path, size[i], apparent[i], files[i], newest[i], own_newest[i], errors[i],
                    bool(f & 1), bool(f & 2), reasons[reason[i]], bool(f & 4), [],
                    device[i], inode[i], own_size[i], own_apparent[i], own_errors[i], link_count[i])
        made[i] = node
        nodes[path] = node
        if p >= 0:
            made[p].children.append(path)
        if f & 8:
            inodes.add((node.device, node.inode))
    scanner.visited += header['visited']
    scanner.bytes += header['bytes']
    scanner.unreadable += header['unreadable']
    scanner.skipped += header['skipped']
    if header['limited']:
        scanner.limited = True
    if count:
        scanner.current = paths[-1]
