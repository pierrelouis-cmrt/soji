"""Agent presets, prompt contract, isolated MCP runs and verdict reuse."""
from __future__ import annotations
import dataclasses
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from .util import atomic_json,read_json,ro_sqlite,inside
from .mcp import SCHEMAS,validate
from .index import IndexStore

PRESETS=json.loads(files('soji_cli').joinpath('data/agents.json').read_text())
ERRORS={
 'model':r'model_not_found|model[^\n]{0,80}not (?:supported|found|available)|unknown model|invalid model',
 'authentication':r'\bnot logged in\b|please run /login|invalid api key|oauth token (?:has )?(?:expired|revoked)|login expired|authentication_(?:error|failed)|failed to authenticate|api error: 401\b|401 unauthorized|missing bearer|no codex credentials|codex login|failed to refresh token|please (?:log ?in|sign ?in)',
 'quota':r'usage limit reached|hit your (?:[a-z]+ )?limit|credit balance (?:is )?too low|out of extra usage|billing_error|spend limit reached|quota exceeded|purchase more credits|credits depleted|insufficient_quota',
 'rate-limit':r'rate_limit_error|api error: (?:429|529|503)\b|overloaded_error|429 too many requests|at capacity|server overloaded',
 'cli':r'(?m)^error: (?:unexpected argument|unknown option|unrecognized (?:argument|option)|invalid value)',
 'sandbox':r'sandbox_apply|sandbox-exec: ',
}


def classify_failure(stdout, stderr):
    # AgentFailure.classify examines bounded output; preserve category order.
    text = stdout[-8000:] + '\n' + stderr[-8000:]
    return next((key for key, pattern in ERRORS.items() if re.search(pattern, text, re.I)), 'no-submission')


def stop_agent(process, grace=5):
    """Cancel the whole isolated process group and reap a stubborn agent."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def fingerprint(f):
    from .cleanup import digest
    return digest({'size':f.size,'newest':f.newest,'files':f.files,'identity':f.identity,'hint':f.hint_id,'rule':f.rule,'tier':f.tier if f.hint_id else 'unmatched'})


IDENTITY_FIELDS = ('device', 'inode', 'type', 'parentDevice', 'parentInode')


def content_fingerprint(f):
    """Measured content plus stable identity; mutable mtime/ctime are excluded.

    Identity is a safety boundary in addition to the three-field content
    policy. Return fresh dictionaries for snapshot storage.
    """
    identity = f.identity or {}
    return {'sizeBytes': f.size, 'newestChange': f.newest, 'fileCount': f.files,
            'identity': {key: identity[key] for key in IDENTITY_FIELDS if key in identity}}


def reusable_verdict(store, f, now, trigger='ordinary'):
    """Return a reusable claim; absence/negative claims return None.

    Raw records use the selection policy only after stable identity
    matches. Legacy stores/rows retain their strict hash and TTL behavior.
    Backlog deliberately checks size alone, ignoring age,
    levels, count and timestamp; this never bypasses local cleanup checks.
    """
    reader = getattr(store, 'verdict_record', None)
    if not callable(reader):
        return store.verdict(f.path, fingerprint(f), now)
    record = reader(f.path)
    if record is None:
        return None
    old = record.get('content')
    if old is None:
        return store.verdict(f.path, fingerprint(f), now)
    if not isinstance(old, dict):
        return None
    current = content_fingerprint(f)
    identity = current['identity']
    if (not all(identity.get(key) is not None for key in IDENTITY_FIELDS)
            or old.get('identity') != identity):
        return None
    claim = record.get('data')
    if not isinstance(claim, dict) or claim.get('path') != f.path:
        return None
    # Malformed persisted measurements fail closed instead of reaching numeric
    # policy comparisons. A nullable newestChange remains a valid measurement.
    import math
    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    for content in (old, current):
        if not all(numeric(content.get(k)) and content[k] >= 0 for k in ('sizeBytes', 'fileCount')):
            return None
        newest = content.get('newestChange')
        if newest is not None and not numeric(newest):
            return None
    if trigger == 'backlog':
        tolerance = max(100_000_000, old['sizeBytes'] // 4)
        return claim if abs(current['sizeBytes'] - old['sizeBytes']) <= tolerance else None
    judged_at = record.get('judgedAt')
    if not numeric(judged_at):
        return None
    return None if judgement_needed(old, current, judged_at, now, claim) else claim


def parse_usage(text):
    usage={'inputTokens':0,'outputTokens':0,'cachedTokens':0,'costUSD':0.0}
    for line in text.splitlines():
        try:obj=json.loads(line)
        except ValueError:continue
        if not isinstance(obj,dict):continue
        value=obj.get('usage')
        if isinstance(value,dict):
            usage['inputTokens']=max(usage['inputTokens'],value.get('input_tokens') or 0)
            usage['outputTokens']=max(usage['outputTokens'],value.get('output_tokens') or 0)
            usage['cachedTokens']=max(usage['cachedTokens'],value.get('cached_input_tokens',value.get('cache_read_input_tokens',0)) or 0)
        if isinstance(obj.get('total_cost_usd'),(int,float)):usage['costUSD']=max(usage['costUSD'],obj['total_cost_usd'])
    return usage


# Cache policy, separate from the stricter identity digest.
# A content fingerprint is sizeBytes/newestChange/fileCount only.
def same_content_fingerprint(old, current):
    """Same cached content: timestamp tolerance is strictly <1s."""
    a, b = old.get('newestChange'), current.get('newestChange')
    return (old['sizeBytes'] == current['sizeBytes'] and
            old['fileCount'] == current['fileCount'] and
            ((a is None and b is None) or (a is not None and b is not None and abs(a-b) < 1)))


def judgement_lapsed(old, current, judged_at, now, *, keep=False):
    """Judgements.lapsed / AgentKeeps.lapsed; strict > boundaries."""
    if now - judged_at > 14 * 86400:
        return True
    if current is None:
        return False
    size = old['sizeBytes']
    tolerance = max(50_000_000, size // 10) if keep else max(100_000_000, size // 4)
    if abs(current['sizeBytes'] - size) > tolerance:
        return True
    if keep and current.get('newestChange') is not None:
        previous = old.get('newestChange')
        # Swift uses Date.distantPast when the old date is absent.
        return previous is None or current['newestChange'] - previous > 3600
    return False


def judgement_needed(old, current, judged_at, now, finding):
    """None means a cached negative judgment, not an absent cache record.

    Caller handles cache misses before invoking this policy. A non-keep claim
    without levels is retried. These functions do not grant cleanup permission.
    """
    if finding is None:
        return now - judged_at > 86400
    keep = finding.get('recommendation') == 'keep'
    if not keep and finding.get('levels') is None:
        return True
    return judgement_lapsed(old, current, judged_at, now, keep=keep)


def decode_submission(value):
    """Salvage valid individual rows.

    The fallback accepts an object containing either array and drops
    undecodable rows. Retain the schema checks on each accepted row.
    """
    if not isinstance(value, dict) or not any(isinstance(value.get(k), list) for k in ('findings', 'processVerdicts')):
        return None
    result = {}
    for key in ('findings', 'processVerdicts'):
        rows = value.get(key, [])
        if not isinstance(rows, list):
            continue
        if len(rows) > SCHEMAS['submit_findings']['properties'][key]['maxItems']:
            return None
        result[key] = []
        for row in rows:
            try:
                validate(row, SCHEMAS['submit_findings']['properties'][key]['items'])
            except ValueError:
                continue
            result[key].append(row)
    return result


def read_submission(run, stdout):
    """Prefer submission.json; recover markers (including fenced JSON) on failure."""
    data = decode_submission(read_json(Path(run) / 'submission.json'))
    if data is not None:
        return data
    texts = [stdout]
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get('result'), str):
            texts.append(obj['result'])
    for text in texts:
        for match in re.finditer(r'SOJI_FINDINGS_BEGIN\s*(.*?)\s*SOJI_FINDINGS_END', text, re.S):
            payload = match.group(1).strip()
            if payload.startswith('```'):
                payload = re.sub(r'^```[^\n]*\n', '', payload)
                payload = re.sub(r'\s*```\s*$', '', payload)
            try:
                data = decode_submission(json.loads(payload))
            except ValueError:
                continue
            if data is not None:
                return data
    return None


def entry_command():
    # Works from source and from a portable .pyz at any working directory.
    entry=Path(sys.argv[0]).resolve()
    if entry.suffix=='.pyz':return [sys.executable,str(entry),'mcp']
    return [sys.executable,str(Path(__file__).resolve().parents[1]/'entrypoint.py'),'mcp']

class AIAnalyzer:
    def __init__(self,state,preset='claude',model=None,effort=None,max_turns=40,max_minutes=10,max_runs_per_day=24,custom_command=None):
        self.state=Path(state).expanduser().resolve();self.preset=next((p for p in PRESETS if p['id']==preset),None)
        if self.preset is None:raise ValueError('Unknown agent preset')
        self.model=model;self.effort=effort;self.max_turns=max_turns;self.max_minutes=max_minutes;self.max_runs_per_day=max_runs_per_day;self.custom_command=shlex.split(custom_command) if isinstance(custom_command,str) else custom_command
    def detect(self):
        if self.preset['id']=='custom':
            if not self.custom_command:raise ValueError('Custom preset needs --command')
            found=shutil.which(self.custom_command[0])
            if not found:raise ValueError('Custom executable not found')
            return found
        for binary in self.preset.get('binaries',[]):
            found=shutil.which(binary)
            if found:return found
            for root in self.preset.get('searchPaths',[]):
                p=Path(os.path.expandvars(os.path.expanduser(root)))/binary
                if p.is_file() and os.access(p,os.X_OK):return str(p)
        raise ValueError('Agent CLI not found: '+self.preset['name'])
    def prompt(self,scanner,findings):
        template=files('soji_cli').joinpath('data/disk-prompt.txt').read_text()
        data=[]
        for f in findings:
            data.append({'path':f.path,'size':f.size,'files':f.files,'group':f.group,'hint':f.hint_id,'rule':f.rule,'defaultLevels':f.levels,'holds':f.holds,'newest':f.newest,'activity':f.last_activity,'evidence':f.evidence})
        return template+'\nIndexed: '+str(scanner.bytes)+' bytes.\n<data name="soji-listed">\n'+json.dumps(data,ensure_ascii=False)+'\n</data>\n'
    def prepare(self,scanner,findings=None):
        self.state.mkdir(parents=True,exist_ok=True)
        run=self.state/'Runs'/(time.strftime('%Y%m%dT%H%M%S')+'-disk-'+uuid.uuid4().hex[:6]);run.mkdir(parents=True,mode=0o700)
        findings=findings if findings is not None else scanner.findings
        (run/'prompt.md').write_text(self.prompt(scanner,findings))
        report=scanner.report('balanced');report['home']=scanner.home
        if getattr(scanner,'database',None):
            with ro_sqlite(scanner.database) as src:
                dst=sqlite3.connect(run/'index.sqlite');src.backup(dst);dst.execute('PRAGMA journal_mode=DELETE');dst.close()
            report['database']=str(run/'index.sqlite')
        atomic_json(run/'report.json',report)
        hidden=[str(Path(scanner.home)/p) for p in ('.ssh','.aws','.gnupg','.kube','Library/Keychains','Library/Mail','Library/Messages')]+[p for p in scanner.protected if os.path.realpath(p)!=os.path.realpath(self.state)]
        atomic_json(run/'context.json',{'roots':scanner.roots,'hiddenPaths':hidden,'kind':'disk','runID':run.name})
        env={'SOJI_REPORT':str(run/'report.json'),'SOJI_RUN_DIR':str(run),'SOJI_HIDDEN_PATHS':json.dumps(hidden)}
        base=entry_command()
        config={'mcpServers':{'soji':{'command':base[0],'args':base[1:],'env':env,**self.preset.get('mcpServerFields',{})}}}
        atomic_json(run/'soji-mcp.json',config)
        executable=self.detect()
        flags=list(self.preset.get('readOnlyArguments',[]))
        if self.max_turns:flags+=self.preset.get('maxTurnsArguments',[])
        if self.model:flags+=self.preset.get('modelArguments',[])
        if self.effort:flags+=self.preset.get('effortArguments',[])
        substitutions={'{prompt}':(run/'prompt.md').read_text(),'{mcp_inline}':'', '{mcp_config}':str(run/'soji-mcp.json'),'{max_turns}':str(self.max_turns),'{model}':self.model or 'default','{effort}':self.effort or 'default','{prompt_file}':str(run/'prompt.md')}
        def expand(items):
            out=[]
            for token in items:
                if token=='{flags}':out.extend(expand(flags));continue
                for key,value in substitutions.items():token=token.replace(key,value)
                out.append(token)
            return out
        argv=[executable,*expand(self.preset.get('runArguments',[]))]
        format=self.preset.get('mcpFormat','mcpServers')
        if self.preset['id']=='codex':
            # Codex's -c accepts TOML, not JSON object syntax.
            inline='mcp_servers.soji={command='+json.dumps(base[0])+',args='+json.dumps(base[1:])+',env={'+','.join(json.dumps(k)+'='+json.dumps(v) for k,v in env.items())+'}'+''.join(','+k+'='+json.dumps(v) for k,v in self.preset.get('mcpServerFields',{}).items())+'}'
            argv=[executable,*expand([t for t in self.preset.get('runArguments',[]) if t!='{mcp_inline}'])]
            argv[1:1]=['-c',inline]
        elif self.preset['id']=='custom':
            argv=[executable,*expand(self.custom_command[1:])]
        if self.preset.get('mcpAttach')=='configFile':
            target=run/'work'/self.preset['mcpConfigFile'];target.parent.mkdir(parents=True,exist_ok=True)
            if format=='toml':
                target.write_text('[mcp_servers.soji]\ncommand = '+json.dumps(base[0])+'\nargs = '+json.dumps(base[1:])+'\n[mcp_servers.soji.env]\n'+'\n'.join(k+' = '+json.dumps(v) for k,v in env.items())+'\n')
            elif format=='opencode':atomic_json(target,{'mcp':{'soji':{'type':'local','command':base,'environment':env,'enabled':True}}})
            else:atomic_json(target,config)
        profile='(version 1)\n(allow default)\n(deny file-write*)\n'
        def q(p):return json.dumps(str(p))
        work=run/'work';work.mkdir(exist_ok=True)
        for p in [run,Path(os.environ.get('TMPDIR','/private/tmp'))]:profile+='(allow file-write* (subpath '+q(p)+'))\n'
        for p in self.preset.get('writablePaths',[]):
            p=os.path.expandvars(os.path.expanduser(p))
            if '$' in p:continue
            if '*' not in p:profile+='(allow file-write* (subpath '+q(p)+'))\n'
            else:
                regex='^'+re.escape(p).replace(r'\*','[^/]*')+'(/.*)?$'
                profile+='(allow file-write* (regex #'+json.dumps(regex)+'))\n'
        # Protect the complete live index and all sidecars. Only the standalone
        # per-run snapshot is readable; no WAL-write exception is granted.
        profile+='(deny file-write* (subpath '+q(self.state)+'))\n(allow file-write* (subpath '+q(run)+'))\n'
        for name in ['index.sqlite','index.sqlite-wal','index.sqlite-shm','index.sqlite-journal','report.json','context.json','soji-mcp.json','prompt.md','sandbox.sb','launch.json']:
            profile+='(deny file-write* (literal '+q(run/name)+'))\n'
        for p in hidden:profile+='(deny file-read* file-write* (subpath '+q(p)+'))\n'
        (run/'sandbox.sb').write_text(profile)
        launch=['/usr/bin/sandbox-exec','-f',str(run/'sandbox.sb'),*argv]
        atomic_json(run/'launch.json',{'argv':launch,'cwd':str(work),'environment':env,'preset':self.preset['id']})
        return run,launch,env
    def run(self,scanner,dry_run=False,trigger='ordinary'):
        store=IndexStore(scanner.database) if getattr(scanner,'database',None) else None
        pending=[];cached=[]
        try:
            for f in scanner.findings:
                prior=reusable_verdict(store,f,time.time(),trigger=trigger) if store else None
                if prior:cached.append(prior)
                else:pending.append(f)
            if not pending:
                self.apply(scanner,cached);return {'cached':len(cached),'executed':False}
            # Bound input. Remaining rows are visible in MCP's persisted index.
            pending=sorted(pending,key=lambda f:f.size,reverse=True)[:200]
            # Capture measured inputs before apply can change tier/rule/identity
            # or replace findings. Never cache a newly nominated path without a
            # corresponding local baseline. Omitted rows are not negative claims.
            baselines={f.path:(fingerprint(f),content_fingerprint(f)) for f in scanner.findings}
            run,argv,env=self.prepare(scanner,pending)
            if dry_run:return {'runDirectory':str(run),'argv':argv,'executed':False,'pending':len(pending)}
            day=time.strftime('%Y-%m-%d');tally=self.state/('agent-runs-'+day+'.json');counts=read_json(tally) or {'count':0}
            if counts['count']>=self.max_runs_per_day:raise ValueError('Daily agent-run limit reached')
            counts['count']+=1;atomic_json(tally,counts)
            start=time.time();run_env=dict(os.environ,**env,**self.preset.get('environment',{}))
            for key in list(run_env):
                if key.startswith('CLAUDE_CODE_') and key not in self.preset.get('environment',{}):run_env.pop(key)
            with (run/'stdout.log').open('w') as stdout,(run/'stderr.log').open('w') as stderr:
                p=subprocess.Popen(argv,cwd=run/'work',env=run_env,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,start_new_session=True,text=True)
                try:p.communicate((run/'prompt.md').read_text(),timeout=self.max_minutes*60)
                except (subprocess.TimeoutExpired,KeyboardInterrupt):stop_agent(p);raise
            data=read_submission(run,(run/'stdout.log').read_text(errors='replace')[-4_000_000:])
            if data is None:
                stderr=(run/'stderr.log').read_text(errors='replace')[-10000:]
                category=classify_failure((run/'stdout.log').read_text(errors='replace'),stderr)
                raise ValueError('Agent ended without valid findings: '+category+'; logs: '+str(run))
            usage=parse_usage((run/'stdout.log').read_text(errors='replace')[-4_000_000:]);usage['seconds']=time.time()-start
            atomic_json(run/'usage.json',usage)
            validate(data,SCHEMAS['submit_findings'])
            self.apply(scanner,cached+data.get('findings',[]))
            if store:
                for finding in data.get('findings',[]):
                    baseline=baselines.get(finding['path'])
                    if baseline is None:continue
                    strict,content=baseline
                    if callable(getattr(store,'verdict_record',None)):
                        store.save_verdict(finding['path'],strict,finding,time.time(),content=content)
                    else:
                        store.save_verdict(finding['path'],strict,finding,time.time())
                with store.db:store.db.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?)',(run.name,start,time.time(),'completed',json.dumps(usage)))
            return {'runDirectory':str(run),'executed':True,'submitted':len(data.get('findings',[])),'cached':len(cached),'exitCode':p.returncode,'usage':usage}
        finally:
            if store:store.close()
    def apply(self,scanner,findings):
        from .engine import Finding,Node
        bypath={f.path:f for f in scanner.findings}
        for data in findings:
            path=os.path.realpath(data['path'])
            if not any(path==r or path.startswith(r.rstrip('/')+'/') for r in scanner.roots):continue
            f=bypath.get(path)
            node=scanner.nodes.get(path)
            if node is not None and (f is None or f.size!=node.size or f.files!=node.files):
                if f is not None:scanner.findings=[old for old in scanner.findings if old is not f]
                f=scanner.classify(node);scanner.findings.append(f);bypath[path]=f
            if f is None:continue
            levels=data.get('levels')
            if isinstance(levels,dict):
                numeric={k:v for k,v in levels.items() if k in ('careful','balanced','aggressive')}
                # A more permissive mode must not become stricter accidentally.
                for stricter,looser in [('careful','balanced'),('balanced','aggressive')]:
                    if stricter in numeric:numeric[looser]=min(numeric.get(looser,numeric[stricter]),numeric[stricter])
                f.levels={**numeric,'reason':levels.get('reason','Agent judgment')}
            if not f.hint_id:
                f.group=data.get('group',f.group);f.label=data.get('title',f.label)
            if not f.hint_id and data.get('regenerable') and data.get('recommendation')=='remove':
                parts={p.casefold() for p in Path(path).parts}
                cache=bool(parts & {'caches','cache','tmp','.cache'})
                marker=Path(path)/'CACHEDIR.TAG'
                try:
                    if marker.is_file() and not marker.is_symlink():
                        with marker.open('rb') as m:cache |= m.read(43).startswith(b'Signature: 8a477f597d28d172789f06886806bc55')
                except OSError:pass
                if cache:f.tier='regenerable';f.list_only=False;f.comes_back=data.get('comesBack','rebuilds')
                else:f.holds.append('Unknown agent-nominated data lacks deterministic cache evidence')
            f.source='both' if f.hint_id else 'agent';f.recommendation=data.get('recommendation','review');f.confidence=data.get('confidence')
            f.evidence.append({'check':'agent','judgment':data})
            # AI may nominate unknown folders but cannot override any local hold,
            # personal-data tier, reviewOnly policy, or specialized integrity rule.
            # cleanCommand is evidence only; the plan uses bound native actions.
        # Prevent double-counting/cleaning a newly split child and its old parent.
        nominated={os.path.realpath(d['path']) for d in findings}
        scanner.findings=[f for f in scanner.findings if not any(p!=f.path and p.startswith(f.path.rstrip('/')+'/') for p in nominated) and not (f.path not in nominated and any(f.path.startswith(p.rstrip('/')+'/') for p in nominated))]
