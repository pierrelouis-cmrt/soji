"""Read-only disk classifier driven by the hint catalog."""
from __future__ import annotations
import bisect
import collections
import dataclasses
import fnmatch
import functools
import hashlib
import json
from importlib.resources import files as resource_files
import os
import sys
from pathlib import Path
import re
import stat
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import time

DATA = resource_files('soji_cli').joinpath('data')
from .levels import MODES, ALIASES, SESSION_FLOOR_SECONDS, normalize_mode  # noqa: E402,F401
from .policy import ACTIVE_USE, PolicyResult  # noqa: E402
MODE_TEXT = {
    'careful': 'Only clearly disposable items; per-item judgments and safety floors apply.',
    'balanced': 'Stale items; preserve costly or uncertain data unless explicitly judged.',
    'aggressive': 'Unused recoverable items; all activity and integrity guards still apply.',
}
PROJECT_MARKERS = ('package.json', 'Package.swift', 'Cargo.toml', 'pyproject.toml', 'setup.py', 'Gemfile', 'pom.xml', 'build.sbt', 'settings.gradle', 'settings.gradle.kts', 'build.gradle', 'build.gradle.kts', 'Podfile', 'pubspec.yaml', 'mix.exs', 'composer.json', 'CMakeLists.txt', 'Makefile', 'deno.json', 'project.godot', 'ProjectSettings')
PRIVATE_NAMES = {'.ssh', '.gnupg', '.aws', '.kube', '.netrc', '.git', '.svn', '.hg'}
PRIVATE_SUFFIXES = ('.photoslibrary', '.photolibrary', '.aplibrary', '.keychain-db')
SECRET_SUFFIXES = ('.pem', '.key', '-keypair.json', '.p12', '.pfx')
PRIVATE_HOME = ('Library/Mail', 'Library/Messages', 'Library/Keychains', 'Library/CloudStorage', 'Library/Mobile Documents', 'Library/Application Support/com.apple.TCC', 'Library/Application Support/Soji')
CLOUD_NAMES = ('Dropbox', 'Google Drive', 'OneDrive', 'Box Sync', 'Box Drive', 'pCloud Drive', 'MEGA', 'Nextcloud', 'ownCloud', 'SynologyDrive', 'Tresorit')
from .installs import ATOMIC, PROJECT_OUTPUT, NEEDS_REAL_PROJECT, capable  # noqa: E402
from .safety import STAGED_PREFIX, staged_ancestor


def within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip('/') + '/')


def human(n: int) -> str:
    value = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(value) < 1000 or unit == 'PB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1000
    return str(n)


@functools.lru_cache(maxsize=None)
def glob_regex(pattern: str) -> re.Pattern:
    """Segment-aware glob: * never crosses /; ** matches zero or more segments."""
    parts = pattern.split('/')
    pieces = []
    for i, part in enumerate(parts):
        if part == '**':
            pieces.append(('/*' if i == 0 else '') + ('(?:[^/]+/)*' if i < len(parts)-1 else '.*'))
        else:
            part_re = fnmatch.translate(part)
            # fnmatch's .* crosses separators; constrain every non-** segment.
            body = part_re[4:-3].replace('.*', '[^/]*').replace('.', '.')
            pieces.append('(?=[^/]*(?:/|$))'+body)
            if i < len(parts)-1: pieces.append('/')
    return re.compile('^' + ''.join(pieces) + '$', re.IGNORECASE)


NO_MATCH = -1


from .models import Node, Finding, SESSION_HINTS


# Rules that make a matched folder one cleanup unit (retention family, device,
# worktree, workspace); such rows are never split around nested hints.
UNIT_RULES = ('keepNewest', 'checkSimulatorDevice', 'checkDeviceBuilds', 'sameIdleAtEveryLevel', 'checkWorkspaceExists')


def generic_container(match) -> bool:
    """A selectable catch-all such as ~/Library/Caches/*.

    When a more specific hint matches inside one of
    these (Homebrew, Playwright, Cypress, browser caches...), the frontier
    descends so the specific rule applies, and the unmatched remainder keeps
    the catch-all classification. Review-only parents already descend.
    """
    if not match:return False
    hint,pattern=match
    # An installed toolchain/extension is one unit: never split it file by file.
    return (pattern.rstrip('/').rsplit('/',1)[-1]=='*' and not hint.get('reviewOnly')
            and hint['tier']!='userData' and not capable(hint,ATOMIC)
            and not any(k in (hint.get('rule') or {}) for k in UNIT_RULES))


class Catalog:
    def __init__(self, home: str):
        self.home = home
        self.hints = json.loads((DATA/'hints.json').read_text())
        self.groups = {g['name']:g for g in json.loads((DATA/'groups.json').read_text())}
        self.by_last = collections.defaultdict(list)
        self.wild = []
        from .locations import cache_locations
        dynamic=collections.defaultdict(list)
        self.locations=cache_locations(home)
        for hint_id,path,source in self.locations:dynamic[hint_id].append(path)
        for hint in self.hints:
            for pattern in hint['patterns']+dynamic[hint['id']]:
                expanded = pattern.replace('~', home, 1) if pattern.startswith('~') else pattern
                record = (glob_regex(expanded), hint, pattern)
                last = expanded.rsplit('/', 1)[-1]
                if any(c in last for c in '*?['): self.wild.append(record)
                else: self.by_last[last.casefold()].append(record)
        # Literal leading segments of each wildcard pattern: an ASCII path that
        # does not start with them cannot match, so its regex is skipped.
        self.wild_prefix = []
        for regex, hint, pattern in self.wild:
            expanded = pattern.replace('~', home, 1) if pattern.startswith('~') else pattern
            literal = []
            for part in expanded.split('/')[:-1]:
                if any(c in part for c in '*?[') or part == '**': break
                literal.append(part)
            prefix = '/'.join(literal) + '/' if literal else ''
            # Literal head/tail of the last segment (`*.mp4`, `blendcache_*`).
            leaf = expanded.rsplit('/', 1)[-1]
            head = re.split(r'[*?\[]', leaf, maxsplit=1)[0]; tail = re.split(r'[*?\]]', leaf)[-1]
            ok = lambda t: t if t.isascii() else ''
            self.wild_prefix.append((ok(prefix).lower(), ok(head).lower(), ok(tail).lower()))
        # Bucketed by literal directory prefix; a path looks up only its own
        # ancestor prefixes, then candidates are restored to catalog order.
        self.wild_buckets = collections.defaultdict(list)
        for i, (record, (prefix, head, tail)) in enumerate(zip(self.wild, self.wild_prefix)):
            self.wild_buckets[prefix].append((i, record, head, tail))
        self.markers_cache = {}
        self.match_cache = {}
        from .installs import InstallTrees
        self.installs = InstallTrees(home, self)
        self.parent_cache = {}
        # Path-only results that later runs may reuse (see `pure`).
        self.records = [r for rs in self.by_last.values() for r in rs] + self.wild
        self.record_index = {(r[1]['id'], r[2]): i for i, r in enumerate(self.records)}
        self.pure = {}
        self.seeded = {}
        self.key = hashlib.sha256(json.dumps([self.hints, self.locations], sort_keys=True).encode()).hexdigest()

    @staticmethod
    def atomic(hint) -> bool:
        return capable(hint, ATOMIC)

    def forget_markers(self):
        """Drop marker listings and the ownership answers derived from them."""
        self.markers_cache.clear();self.installs.forget()

    def forget_filesystem_facts(self):
        """Also drop cached matches: they may depend on the forgotten markers."""
        self.forget_markers();self.match_cache.clear()

    def conditions_hold(self, path: str, hint) -> bool:
        """The hint's marker conditions (contains / unless / ancestor) at `path`."""
        p=Path(path)
        if hint.get('onlyIfContains') and not self.exists(p,hint['onlyIfContains']):return False
        if hint.get('unlessContains') and self.exists(p,hint['unlessContains']):return False
        # Ancestor markers may sit in up to four ancestors.
        if hint.get('onlyIfAncestorContains') and not any(self.exists(a,hint['onlyIfAncestorContains']) for a in list(p.parents)[:4]):return False
        return True

    def exists(self, folder: Path, markers: list[str]) -> bool:
        key=(str(folder),tuple(markers))
        if key not in self.markers_cache:
            try:
                names = os.listdir(folder)
                self.markers_cache[key] = any(
                    (any(fnmatch.fnmatchcase(n.casefold(), marker.casefold()) for n in names)
                     if '/' not in marker else any(folder.glob(marker))) for marker in markers)
            except OSError: self.markers_cache[key] = False
        return self.markers_cache[key]

    def match(self, path: str):
        # Results depend on the path and on cached marker listings only.
        try: return self.match_cache[path]
        except KeyError: pass
        result = self.match_cache[path] = self._match(path)
        return result

    def _parent_candidates(self, parent: str):
        """Wildcard records whose literal prefix is `parent` or one of its
        ancestors, in catalog order; shared by every entry of a folder."""
        found = self.parent_cache.get(parent)
        if found is None:
            buckets = self.wild_buckets; found = list(buckets.get('', ()))
            k = parent.find('/')
            while k >= 0:
                hits = buckets.get(parent[:k+1])
                if hits: found += hits
                k = parent.find('/', k+1)
            found.sort(key=lambda x: x[0])
            self.parent_cache[parent] = found
        return found

    def _candidates(self, path: str, name: str):
        exact = self.by_last.get(name.casefold())
        if not path.isascii():
            return [*(exact or ()), *self.wild]
        low = path.lower(); cut = low.rfind('/'); leaf = low[cut+1:]
        wild = [record for _, record, head, tail in self._parent_candidates(low[:cut+1])
                if leaf.startswith(head) and leaf.endswith(tail)]
        return [*exact, *wild] if exact else wild

    def _match(self, path: str):
        # A seeded result came from the same catalog (Catalog.key) and the same
        # path string, and depends on nothing else: no marker condition decided it.
        code = self.seeded.get(path)
        if code is not None:
            self.pure[path] = code
            if code == NO_MATCH: return None
            record = self.records[code]
            return record[1], record[2]
        name = os.path.basename(path) if not path.endswith('/') else Path(path).name
        candidates = self._candidates(path, name)
        if not candidates:
            self.pure[path] = NO_MATCH
            return None
        pure=True
        for regex,hint,pattern in candidates:
            if not regex.fullmatch(path): continue
            if hint.get('onlyIfContains') or hint.get('unlessContains') or hint.get('onlyIfAncestorContains'):pure=False
            if not self.conditions_hold(path,hint):continue
            if capable(hint,PROJECT_OUTPUT) and pattern.startswith('**/'):
                # Project output only exists in projects: never inside installed
                # software, and dependencies only in a real (locked/VCS) project.
                pure=False
                if not self.installs.project_area(path) or self.installs.containing(path):continue
                if capable(hint,NEEDS_REAL_PROJECT) and not self.installs.real_project(path):continue
            if pure:self.pure[path]=self.record_index[(hint['id'],pattern)]
            return hint,pattern
        if pure:self.pure[path]=NO_MATCH
        return None

    def seed(self, key, codes):
        """Reuse path-only results saved by a previous run of the same catalog."""
        if key == self.key: self.seeded = codes


class Scanner:
    def __init__(self, roots: list[str], *, home: str | None = None, protected=(), max_files=2_000_000, max_seconds=300, min_bytes=1_000_000, context=True, recent_activity_hours=0, inherit_hint=None, catalog=None, pin_roots=None, live_pins=False, tick_trash=False, walk_backend='auto'):
        if walk_backend not in ('auto','native','python'):raise ValueError('Unknown walk backend: '+str(walk_backend))
        self.inherit_hint=inherit_hint
        # Project pins span this policy scope; live_pins rediscovers them on the
        # filesystem rather than trusting this walk's nodes.
        self.pin_roots=list(pin_roots) if pin_roots else None;self.live_pins=live_pins
        self.tick_trash=tick_trash;self.walk_backend=walk_backend
        # Codex writer-lock names; None means discover them when rows are built.
        self.writer_ids=None
        self.home=os.path.realpath(home or str(Path.home()))
        cleaned=sorted(set(os.path.realpath(os.path.expanduser(p)) for p in roots))
        self.roots=[p for p in cleaned if not any(p != q and within(p,q) for q in cleaned)]
        self.protected=[os.path.realpath(os.path.expanduser(p)) for p in protected]
        self.catalog=catalog if catalog is not None else Catalog(self.home)
        self.nodes: dict[str,Node]={}
        self.findings: list[Finding]=[]
        self.cancel=threading.Event()
        self.done=False;self.error='';self.current='';self.visited=0;self.bytes=0;self.unreadable=0
        self.skipped=0;self.max_files=max_files;self.max_seconds=max_seconds;self.min_bytes=min_bytes
        self.started=0.;self.finished=0.;self.now=time.time();self.limited=False
        self.recent_activity_hours=max(0,float(recent_activity_hours))
        self.context=context;self.processes=[];self.open_paths=[];self.context_warnings=[]
        self._inodes=set();self._git_cache={}
        self._private_home=(None,())
        self.activity=None;self.apps=None;self.tools=None;self.specialized=None;self.git=None
        self.progress={'phase':'scan','completed':0,'total':None,'path':''}

    can_clean=True

    def new_scan(self,refresh=False):
        from .scancontrol import ScanConfiguration
        config=ScanConfiguration.of(self)
        return type(self)(list(config.roots),**config.options)

    @staticmethod
    def revalidate_target(spec, context):
        from .revalidation import revalidate_target
        return revalidate_target(spec, context)

    def set_progress(self,phase,completed=0,total=None,path=''):
        self.progress={'phase':phase,'completed':completed,'total':total,'path':path}

    def private(self,path: str) -> str:
        p=Path(path) if path.endswith('/') else None
        name=p.name if p is not None else os.path.basename(path)
        if any(within(path,r) for r in self.protected): return 'User protected path'
        if name in PRIVATE_NAMES: return 'Credentials or repository metadata; contents not scanned'
        if name.lower().endswith(PRIVATE_SUFFIXES):return 'Personal library; contents not scanned'
        if self._private_home[0]!=self.home:self._private_home=(self.home,[os.path.join(self.home,r) for r in PRIVATE_HOME])
        if any(within(path,r) for r in self._private_home[1]):return 'Private or cloud data; contents not scanned'
        if any(name == cloud or name.startswith(cloud+' ') or name.startswith(cloud+'-') for cloud in CLOUD_NAMES):return 'Cloud-synced folder; contents not scanned'
        if name.lower() in ('memory','memories') and any(x in path for x in ['/.claude/', '/.codex/', '/.cursor/']):return 'Agent memory; contents not scanned'
        if name.endswith('.app'):return 'Installed application bundle; contents not scanned'
        return ''

    def collect_context(self):
        if not self.context:
            self.context_warnings.append('Process and open-file checks disabled');return
        try:
            r=subprocess.run(['/bin/ps','-axo','comm='],capture_output=True,text=True,timeout=5)
            if r.returncode:raise OSError('ps failed')
            self.processes=[l.strip().casefold() for l in r.stdout.splitlines() if l.strip()]
        except (OSError,subprocess.TimeoutExpired):self.context_warnings.append('Running processes unavailable')
        try:
            r=subprocess.run(['/usr/sbin/lsof','-nP','-w','-a','-u',str(os.getuid()),'-F','pn'],capture_output=True,text=True,timeout=8)
            if r.returncode not in (0,1) or not r.stdout:raise OSError('lsof unavailable')
            self.open_paths=sorted(set(l[1:].removesuffix(' (deleted)') for l in r.stdout.splitlines() if l.startswith('n/')))
        except (OSError,subprocess.TimeoutExpired):self.context_warnings.append('Open-file check unavailable; activity only partially verified')

    def budget(self) -> bool:
        if self.cancel.is_set():return False
        if self.visited >= self.max_files or time.monotonic()-self.started>self.max_seconds:
            self.limited=True;return False
        return True

    def visit(self,path: str, depth=0, device=None, _stat=None) -> Node:
        node=Node(path);self.nodes[path]=node;self.current=path
        if not self.budget():node.errors=1;node.own_errors=1;node.reason='Scan stopped before measuring';return node
        try:s=os.lstat(path) if _stat is None else _stat
        except OSError:s=None
        if s is None or isinstance(s,OSError):
            node.errors=1;node.own_errors=1;node.reason='Unreadable entry';self.unreadable+=1;return node
        self.visited+=1
        if self.visited%128==1:self.set_progress('scan',self.visited,path=path)
        node.device=s.st_dev;node.inode=s.st_ino
        # Birth time approximates date added; ctime is not creation time on Unix.
        stamp=max(s.st_mtime,getattr(s,'st_birthtime',0))
        node.newest=node.own_newest=stamp
        node.directory=stat.S_ISDIR(s.st_mode)
        if stat.S_ISLNK(s.st_mode):
            node.reason='Symlink; not followed';node.files=1;node.size=getattr(s,'st_blocks',0)*512;node.apparent=s.st_size;node.own_size=node.size;node.own_apparent=node.apparent;self.bytes+=node.size;self.skipped+=1;return node
        if not node.directory:
            if stat.S_ISREG(s.st_mode):
                key=(s.st_dev,s.st_ino)
                node.files=1
                node.link_count=max(1,s.st_nlink)
                node.own_size=(getattr(s,'st_blocks',0)*512)//node.link_count;node.own_apparent=s.st_size
                node.size=node.own_size;self.bytes+=node.size
                if key not in self._inodes:
                    self._inodes.add(key);node.apparent=s.st_size
                name=os.path.basename(path)
                node.secret=name.startswith('.env') or name.endswith(SECRET_SUFFIXES) or name in ('credentials.json','id_rsa','id_ed25519')
            return node
        reason=self.private(path)
        if reason or depth>=128 or (device is not None and s.st_dev!=device):
            node.skipped=True;node.reason=reason or 'Mount boundary or depth limit; contents not scanned';self.skipped+=1;return node
        # Directory blocks count too; hardlinks are counted once per scan.
        node.size=getattr(s,'st_blocks',0)*512;node.apparent=s.st_size;self.bytes+=node.size
        node.own_size=node.size;node.own_apparent=node.apparent
        # Children are stat'ed relative to an open directory descriptor
        # (fstatat), which avoids re-resolving every ancestor per entry.
        entries=[];failed=False
        try:
            fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0))
            try:
                with os.scandir(fd) as it:
                    for entry in it:
                        name=entry.name
                        try:entries.append((name,os.stat(name,dir_fd=fd,follow_symlinks=False)))
                        except OSError as e:entries.append((name,e))
            finally:os.close(fd)
        except OSError:failed=True
        try:
            for name,child_stat in entries:
                    if not self.budget():node.errors+=1;node.own_errors+=1;break
                    child_path=os.path.join(path,name)
                    child=self.visit(child_path,depth+1,s.st_dev,child_stat)
                    node.children.append(child_path)
                    node.size+=child.size;node.apparent+=child.apparent;node.files+=child.files
                    node.newest=max(node.newest,child.newest)
                    node.errors+=child.errors;node.secret |= child.secret
                    # Skipped descendants make candidate size/safety incomplete.
                    if child.skipped:node.skipped=True
        except OSError:failed=True
        if failed:node.errors+=1;node.own_errors+=1;self.unreadable+=1
        return node

    def walk(self,roots):
        """Measure roots [(path, depth, device, stop_node)] like visit().

        The native bulk walker produces identical nodes much faster; visit()
        is the reference and the fallback. stop_node=False roots are skipped
        once the budget is spent (Scanner.run); True roots get a "stopped" row.
        """
        from . import walker
        if self.walk_backend!='python' and not self._inodes and walker.available(self) and walker.walk(self,roots):return
        if self.walk_backend=='native':raise RuntimeError('Native walk unavailable')
        for path,depth,device,stop_node in roots:
            if not stop_node and not self.budget():break
            self.visit(path,depth,device)

    def project_for(self,path: str) -> str | None:
        for parent in list(Path(path).parents)[:8]:
            if str(parent)=='/':break
            if self.catalog.exists(parent,list(PROJECT_MARKERS)) or (parent/'.git').exists():return str(parent)
        return None

    def project_age(self,project: str) -> float | None:
        root=self.nodes.get(project)
        if not root:return None
        # Exclude output/dependencies when judging the source project's activity.
        stamps=[root.own_newest]
        for p in root.children:
            if Path(p).name in ('.git','node_modules','target','.build','.venv','venv','Pods','build','dist','.next'):continue
            stamps.append(self.nodes[p].newest)
        return max(0,(self.now-max(stamps))/3600)

    def running_inside(self,path: str) -> str:
        """Executable path of a running process located in `path`, or ''."""
        if getattr(self,'_exe_source',None) is not self.processes:
            self._exe_source=self.processes
            # ps reports the path as launched: a program started through a
            # symlink lives where the link resolves. Keep both spellings.
            exes=set()
            for p in self.processes:
                if isinstance(p,str) and p.startswith('/'):
                    exes.add(p.casefold())
                    try:exes.add(os.path.realpath(p).casefold())
                    except (OSError,ValueError):pass
            self._exes=sorted(exes)
        keys=[path.casefold().rstrip('/')]
        try:keys.append(os.path.realpath(path).casefold().rstrip('/'))
        except (OSError,ValueError):pass
        for key in dict.fromkeys(k for k in keys if k):
            i=bisect.bisect_left(self._exes,key+'/')
            if i<len(self._exes) and self._exes[i].startswith(key+'/'):return self._exes[i]
            i=bisect.bisect_left(self._exes,key)
            if i<len(self._exes) and self._exes[i]==key:return self._exes[i]
        return ''

    def is_open(self,path: str) -> bool:
        i=bisect.bisect_left(self.open_paths,path)
        # Exact path and descendants; bisect again for the directory prefix.
        if i<len(self.open_paths) and self.open_paths[i]==path:return True
        i=bisect.bisect_left(self.open_paths,path.rstrip('/')+'/')
        return i<len(self.open_paths) and within(self.open_paths[i],path)

    def inherited_match(self,path: str):
        """Re-establish `inherit_hint` for a root split out of a catch-all row.

        Only the hint the caller already holds (a plan item) is accepted, and
        only when the nearest matched ancestor is that same generic hint, so a
        root never acquires a classification it did not have when planned.
        """
        if not self.inherit_hint or self.catalog.match(path):return None
        for parent in Path(path).parents:
            match=self.catalog.match(str(parent))
            if match:return match if match[0]['id']==self.inherit_hint and generic_container(match) else None
        return None

    def staged_inside(self,path: str) -> str | None:
        """A measured `.soji-removing-*` object at or below path (cleanup.Cleaner.move staging)."""
        cache=getattr(self,'_staged_cache',None)
        if cache is None or cache[0]!=len(self.nodes):
            cache=(len(self.nodes),[p for p in self.nodes if os.path.basename(p).startswith(STAGED_PREFIX)])
            self._staged_cache=cache
        return staged_ancestor(path) or next((p for p in cache[1] if within(p,path)),None)

    def classify(self,node: Node,match=None) -> Finding:
        match=match or self.catalog.match(node.path)
        if match:
            hint,pattern=match
            f=Finding(node.path,node.size,node.apparent,node.files,node.newest,hint['group'],hint['label'],hint['id'],hint['tier'],hint['comesBack'],hint.get('rule',{}),hint.get('ruleSummary',''),hint.get('reviewOnly',False),matched_pattern=pattern)
        else:
            name=Path(node.path).name.lower()
            if not node.directory:
                group='Large media files' if name.endswith(('.mov','.mp4','.mkv','.wav','.aiff','.mp3','.jpg','.heic','.png')) else 'Downloads and installers' if name.endswith(('.dmg','.pkg','.xip','.zip','.tar','.gz','.download','.part')) else 'Other files'
            else:group='Other folders'
            f=Finding(node.path,node.size,node.apparent,node.files,node.newest,group,Path(node.path).name or '/',smart_rule='No hint matched; review only')
        from .safety import agent_worktree_boundary, WORKTREE_DISABLED
        if f.group=='Agent worktrees' or agent_worktree_boundary(node.path,self.home,self.catalog):
            f.holds.append(WORKTREE_DISABLED)
        f.recent_activity_hours=self.recent_activity_hours
        staged=self.staged_inside(node.path)
        if staged:f.holds.append(f'Contains a Sōji staged object kept after a failed permanent removal ({staged}); it may be displaced user data: review it with `soji recover`, never cleaned automatically')
        if node.errors:f.holds.append(f'Incomplete measurement ({node.errors} errors or scan limit)')
        if node.skipped:f.holds.append(node.reason or 'Contains an excluded or unreadable subtree')
        if node.secret:f.holds.append('Contains credential or environment-file names')
        if self.now-node.newest<300:f.holds.append('Changed or created within the last 5 minutes')
        if self.is_open(node.path):f.hold('File open or process working in this folder',ACTIVE_USE)
        program=self.running_inside(node.path)
        if program:f.hold('A running program is installed here: '+program,ACTIVE_USE)
        install=self.catalog.installs.containing(node.path)
        if install:
            # Shipped code of installed software: only the whole install root,
            # through its own rule, can ever be a cleanup unit.
            f.holds.append(f'Inside installed software ({install[1]}: {install[0]}); only the whole install can be cleaned')
            f.evidence.append({'check':'installTree','root':install[0],'reason':install[1]})
        running=[]
        for proc in f.rule.get('notWhileRunning',[]):
            if any(Path(p).name==proc.casefold() or p.endswith('/'+proc.casefold()) for p in self.processes):running.append(proc)
        if running:f.hold('Running: '+', '.join(running),ACTIVE_USE)
        project=(node.path if f.group=='Agent worktrees' else self.project_for(node.path)) if f.hint_id and (f.rule.get('minProjectIdleDays') or f.group in ('Build output','Project dependencies','Agent worktrees')) else None
        if project:
            f.project_idle_hours=self.project_age(project)
            # Safety extension: agent or
            # editor activity recorded at the owning project root also counts
            # as project use. Descendant-only last() is kept; the query is just
            # rooted at the project, and only the project clock is affected.
            used=self.activity.last(project) if self.activity and project!=node.path else None
            if used:
                idle=max(0,(self.now-used.at)/3600)
                f.evidence.append({'check':'projectActivity','project':project,'source':used.source,'at':used.at,'basis':'safety extension: activity at owning project root'})
                if f.project_idle_hours is None or idle<f.project_idle_hours:f.project_idle_hours=idle
                if self.now-used.at<max(300,self.recent_activity_hours*3600):f.hold('Coding agent or editor used this project recently',ACTIVE_USE)
            state=self.git.inspect(project,worktree=f.group=='Agent worktrees') if self.git else {}
            if state.get('reason'):f.holds.append(state['reason'])
            f.evidence.append({'check':'git','state':state})
        if f.rule.get('notWhileOwnerRuns') and self.apps is not None and not self.apps.running_available:
            f.holds.append('Owning application running status unknown; running-app inventory unavailable')
        if self.specialized:self.specialized.evaluate(f)
        if self.context_warnings:f.holds.extend(self.context_warnings)
        from .identity import file_identity
        try:
            f.identity=file_identity(f.path)
            if f.identity['type']==stat.S_IFLNK:f.holds.append('Symlink itself is never a cleanup target')
        except OSError:f.holds.append('File identity unavailable')
        f.thresholds={'minIdleDays':f.rule.get('minIdleDays'),'minProjectIdleDays':f.rule.get('minProjectIdleDays')}
        return f

    def run(self):
        self.started=time.monotonic()
        try:
            # Process/open-file snapshots (subprocesses) overlap the walk.
            with ThreadPoolExecutor(1) as pool:
                context=pool.submit(self.collect_context)
                self.walk([(root,0,None,False) for root in self.roots])
                context.result()
            self._build_findings()
        except Exception as exc:self.error=f'{type(exc).__name__}: {exc}'
        finally:
            self.set_progress('done',1,1);self.done=True;self.finished=time.monotonic()

    def _build_findings(self,inventories=None):
        self.prepare_policy(inventories)
        self.set_progress('categorize',1,4,'Matching categories')
        rows=self.frontier_rows()
        self.set_progress('categorize',2,4,'Sorting session and Trash catalogs')
        from . import catalogs
        self.findings=self.finish_rows(catalogs.expand_catalogs(self,rows))

    def prepare_policy(self,inventories=None):
        """Build the activity/app/tool inventories every rule consults.

        `inventories` reuses an (activity, apps, tools) snapshot taken moments
        earlier by the same cleanup batch.
        """
        from .activity import ActivityIndex
        from .apps import AppCatalog,InstalledTools
        from .specialized import SpecializedRules
        from .gitstate import GitInspector
        self.now=time.time();self.findings=[]
        self.set_progress('categorize',0,4,'Checking activity and apps')
        self.git=GitInspector()
        if inventories is not None:
            self.activity,self.apps,self.tools=inventories
        elif self.context:
            # Independent local inventories; their file and subprocess I/O overlaps.
            with ThreadPoolExecutor(3) as pool:
                activity=pool.submit(lambda:ActivityIndex(self.home).build())
                apps=pool.submit(lambda:AppCatalog(self.home,self.processes).build())
                tools=pool.submit(lambda:InstalledTools(self.home).build())
                self.activity=activity.result();self.apps=apps.result();self.tools=tools.result()
        else:
            self.activity=ActivityIndex(self.home);self.apps=AppCatalog(self.home);self.tools=InstalledTools(self.home)
        self.specialized=SpecializedRules(self,self.apps,self.activity,self.tools) if self.context else None
        return self.activity,self.apps,self.tools

    def frontier_rows(self):
        """Every row is measured once. Select a non-overlapping frontier: known
        hint roots first; otherwise recurse to expose meaningful children."""
        rows=[]
        below=collections.defaultdict(set)  # ancestor -> hint ids matched beneath it
        for path,n in self.nodes.items():
            match=self.catalog.match(path)
            if match:
                for parent in Path(path).parents:
                    ids=below[str(parent)]
                    if match[0]['id'] in ids: break
                    ids.add(match[0]['id'])
        known_ancestors=below
        def frontier(path,level=0,inherited=None):
            n=self.nodes[path]
            if n.size<self.min_bytes and not n.reason:return
            match=self.catalog.match(path) or inherited
            descend_review=bool(match and (match[0].get('reviewOnly') or match[0]['tier']=='userData') and path in known_ancestors and match[0]['id'] not in ('claude-sessions','codex-sessions','trash')
                                and not self.catalog.atomic(match[0]))
            split=bool(not descend_review and generic_container(match) and below.get(path,set())-{match[0]['id']})
            if (match and not descend_review and not split) or not n.children or n.reason:
                rows.append(self.classify(n,match));return
            if level>=4 and n.size<500_000_000 and path not in known_ancestors:
                rows.append(self.classify(n,match));return
            if n.children:
                own=n.size-sum(self.nodes[c].size for c in n.children)
                if own>=self.min_bytes:
                    direct=dataclasses.replace(n,size=own,apparent=own,children=[],directory=False)
                    f=self.classify(direct);f.label='Directory metadata';f.group='Other files';rows.append(f)
                for c in n.children:frontier(c,level+1,match if split else None)
        for root in self.roots:
            if root in self.nodes:frontier(root,0,self.inherited_match(root))
        rows.sort(key=lambda f:f.size,reverse=True)
        return rows

    def finish_rows(self,rows):
        """Staged-object holds, native metadata and final order for built rows."""
        for f in rows:
            staged=next((hit for p in [f.path,*[m['path'] for m in f.members]] if (hit:=self.staged_inside(p))),None)
            if staged and not any('staged object' in h for h in f.holds):
                f.holds.append('Sōji staged object requires manual review: '+staged)
        self.set_progress('categorize',3,4,'Checking file metadata')
        if self.context:
            from .platform import native
            # 512 rows per helper launch, four launches at a time.
            batches=[rows[start:start+512] for start in range(0,len(rows),512)]
            with ThreadPoolExecutor(4) as pool:
                answers=list(pool.map(lambda batch:native('metadata',*[f.path for f in batch],timeout=30),batches))
            for batch,values in zip(batches,answers):
                if isinstance(values,list):
                    bypath={v['path']:v for v in values}
                    for f in batch:
                        meta=bypath.get(f.path,{})
                        f.date_added=meta.get('added') or None
                        if meta.get('cloud'):f.holds.append('Cloud-managed or online-only item')
                        if meta:f.evidence.append({'check':'nativeMetadata',**meta})
        rows.sort(key=lambda f:f.size,reverse=True)
        if self.context and not self.apps.running_available:
            self.context_warnings.append('Running-app inventory unavailable; owner-running checks unknown')
        self.set_progress('categorize',4,4,'Categories ready')
        return rows

    def decisions(self,mode):
        from .safety import agent_worktree_boundary, WORKTREE_DISABLED
        for f in self.findings:
            if f.group=='Agent worktrees' or agent_worktree_boundary(f.path,self.home,self.catalog):
                if WORKTREE_DISABLED not in f.holds:f.holds.append(WORKTREE_DISABLED)
                f.action={}
            f.recent_activity_hours=self.recent_activity_hours
            f.selected,f.decision=f.decide(mode,self.now)
        return self.findings

    def report(self,mode):
        findings=self.decisions(mode)
        return {'format':'soji/1','roots':self.roots,'home':self.home,'mode':mode,'modeDescription':MODE_TEXT[ALIASES.get(mode,mode)], 'source':'375 hints; native rules, activity, index, AI integration and guarded cleanup', 'scannedAt':self.now,'visited':self.visited,'indexedEntries':len(self.nodes),'allocatedBytes':self.bytes,'selectedBytes':sum(f.size for f in findings if f.selected),'unreadable':self.unreadable,'excludedSubtrees':self.skipped,'limited':self.limited or self.cancel.is_set(),'error':self.error,'contextWarnings':self.context_warnings,'findings':[dataclasses.asdict(f) for f in findings]}
