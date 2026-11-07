from __future__ import annotations
import argparse
import dataclasses
import json
import math
import os
from pathlib import Path
import signal
import sys
from .engine import Scanner, MODES, human
from .util import atomic_json,read_json

COMMANDS={'ai','scan','analyse','plan','clean','undo','journal','watch','mcp','agents','activity','versions','runtimes','routines','processes','rules','apps','uninstall','auto','recover'}

def emit(value):print(json.dumps(value,indent=2,ensure_ascii=False))

def main():
    argv=sys.argv[1:]
    if '--ai' in argv and (not argv or argv[0] not in COMMANDS):
        argv=['ai','brief',*[a for a in argv if a!='--ai']]
    action=argv.pop(0) if argv and argv[0] in COMMANDS else 'scan'
    p=argparse.ArgumentParser(prog='soji '+action,description='Sōji: reconstructed disk analysis, persistent index, AI and verified cleanup.')
    p.add_argument('--state',default=str(Path.home()/'Library/Application Support/Soji'),help='Independent application state directory')
    if action=='mcp':
        p.add_argument('--report',default=os.environ.get('SOJI_REPORT'));args=p.parse_args(argv)
        from .mcp import MCPServer
        if not args.report:p.error('MCP needs --report or SOJI_REPORT')
        report=read_json(args.report)
        if not isinstance(report,dict):p.error('Invalid report')
        MCPServer(report,os.environ.get('SOJI_RUN_DIR'),json.loads(os.environ.get('SOJI_HIDDEN_PATHS','[]'))).serve();return 0
    if action=='ai':return ai_command(p,argv)
    if action in ('clean','undo','journal','recover'):
        p.add_argument('target',nargs='?');p.add_argument('--apply',action='store_true');p.add_argument('--permanent',action='store_true');p.add_argument('--execute-tools',action='store_true')
        args=p.parse_args(argv)
        from .cleanup import Cleaner,validate_plan
        cleaner=Cleaner(args.state)
        if action=='journal':emit(cleaner.entries());return 0
        if action=='recover':emit(cleaner.recover(args.apply));return 0
        if not args.target:p.error('A plan path or journal entry ID is required')
        if action=='undo':
            if not args.apply:p.error('Restore requires --apply')
            emit(cleaner.undo(args.target));return 0
        plan=validate_plan(read_json(args.target))
        if not args.apply:emit({'review':plan,'executed':False});return 0
        result=cleaner.apply(plan,permanent=args.permanent,execute_tools=args.execute_tools);emit(result)
        return 1 if result['failed'] else 0
    if action in ('apps','uninstall'):
        p.add_argument('target',nargs='?');p.add_argument('--output');p.add_argument('--home',default=str(Path.home()));args=p.parse_args(argv)
        if action=='apps':
            from .apps import AppCatalog
            emit(AppCatalog(args.home).build().apps)
        else:
            if not args.target:p.error('App path, bundle identifier, or name required')
            from .uninstall import uninstall_plan
            result=uninstall_plan(args.target,args.home)
            if args.output:atomic_json(args.output,result)
            emit(result)
        return 0
    if action=='agents':
        args=p.parse_args(argv)
        from .ai import PRESETS,AIAnalyzer
        result=[]
        for preset in PRESETS:
            try:path=AIAnalyzer(args.state,preset=preset['id']).detect()
            except ValueError:path=None
            result.append({'id':preset['id'],'name':preset['name'],'path':path,'preset':preset})
        emit(result);return 0
    if action in ('activity','versions','runtimes','rules','processes'):
        p.add_argument('target',nargs='?');p.add_argument('--home',default=str(Path.home()));p.add_argument('--plan',action='store_true');p.add_argument('--output');args=p.parse_args(argv)
        if action=='activity':
            from .activity import ActivityIndex
            emit(ActivityIndex(args.home).build().report(args.target))
        elif action=='versions':
            if not args.target:p.error('Document path required')
            from .catalogs import document_versions
            if args.plan:
                from .nativeplans import versions_plan
                result=versions_plan(args.target,args.home)
            else:result=document_versions(args.target)
            if args.output:atomic_json(args.output,result)
            emit(result)
        elif action=='runtimes':
            from .catalogs import runtime_catalog
            if args.plan:
                from .nativeplans import runtimes_plan
                result=runtimes_plan(args.home)
            else:result=runtime_catalog()
            if args.output:atomic_json(args.output,result)
            emit(result)
        elif action=='rules':
            from .engine import Catalog
            hints=Catalog(args.home).hints;emit([h for h in hints if not args.target or args.target in h['id'] or args.target in h['group']])
        else:
            from .mcp import MCPServer
            emit(MCPServer({'roots':[args.home]}).call('processes',{'sort':args.target or 'cpu'}))
        return 0
    if action=='routines':
        p.add_argument('operation',choices=['list','save','run']);p.add_argument('target',nargs='?');p.add_argument('--apply',action='store_true');args=p.parse_args(argv)
        from .routines import Routines
        routines=Routines(args.state)
        if args.operation=='list':emit(routines.list());return 0
        if not args.target:p.error('Routine JSON file or ID required')
        if args.operation=='save':emit(routines.save(read_json(args.target)));return 0
        routine=next((r for r in routines.list() if r['id']==args.target),None)
        if not routine:p.error('Unknown routine ID')
        from .index import IndexedScanner
        scanner=IndexedScanner(routine['paths'],database=Path(args.state)/'index.sqlite',refresh=True);scanner.run()
        if scanner.error:raise ValueError(scanner.error)
        emit(routines.run(routine,scanner,args.apply));return 0
    p.add_argument('paths',nargs='*',help='Scan roots; default: home directory')
    p.add_argument('--mode',choices=MODES,default='balanced')
    p.add_argument('--json',action='store_true');p.add_argument('--plain',action='store_true')
    p.add_argument('--output',help='JSON result/plan path')
    p.add_argument('--protect',action='append',default=[])
    p.add_argument('--max-seconds',type=float,default=300);p.add_argument('--max-files',type=int,default=1000000);p.add_argument('--min-mb',type=float,default=1)
    p.add_argument('--recent-activity-hours',type=float,default=0,help='Minimum recent activity exclusion, in hours (at least 5 minutes)')
    p.add_argument('--no-context',action='store_true');p.add_argument('--home');p.add_argument('--demo',action='store_true')
    p.add_argument('--no-index',action='store_true');p.add_argument('--refresh',action='store_true')
    p.add_argument('--tick-trash',action='store_true');p.add_argument('--agent',default='claude');p.add_argument('--model');p.add_argument('--effort');p.add_argument('--command',help='Custom agent command; argv parsing only, no shell')
    p.add_argument('--dry-run',action='store_true',help='Prepare AI prompt/config without launching an agent')
    p.add_argument('--auto-settings',help='Auto-mode configuration JSON');p.add_argument('--apply',action='store_true');p.add_argument('--permanent',action='store_true')
    p.add_argument('--method',choices=['trash','permanent'],default='trash');p.add_argument('--interval',type=float,default=5)
    p.add_argument('--version',action='version',version='Sōji 0.4.0')
    args=p.parse_args(argv)
    if args.max_files<1 or args.max_seconds<=0 or args.min_mb<0:p.error('Invalid scan limits')
    if not math.isfinite(args.recent_activity_hours) or args.recent_activity_hours<0:p.error('Invalid recent activity hours')
    roots=args.paths or [str(Path.home())]
    for path in roots:
        if not Path(path).expanduser().is_dir():p.error('Not a directory: '+path)
    options=dict(home=args.home,protected=args.protect+[args.state],max_files=args.max_files,max_seconds=args.max_seconds,min_bytes=int(args.min_mb*1000000),context=not args.no_context,recent_activity_hours=args.recent_activity_hours)
    if args.no_index:scanner=Scanner(roots,**options)
    else:
        from .index import IndexedScanner
        scanner=IndexedScanner(roots,database=Path(args.state)/'index.sqlite',refresh=args.refresh,**options)
    scanner.tick_trash=args.tick_trash
    if args.demo:
        from .demo import DemoScanner
        scanner=DemoScanner()
    if action=='watch':
        if args.no_index:p.error('Watch requires persistent indexing')
        signal.signal(signal.SIGINT,lambda *_:scanner.cancel.set())
        scanner.watch(max(1,args.interval),lambda r:print(json.dumps(r),flush=True));return 0
    interactive=action=='scan' and not args.json and not args.plain and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive:
        from .tui import run_tui
        run_tui(scanner,args.mode,args.output);return 0
    scanner.run()
    if scanner.error:raise ValueError(scanner.error)
    if action=='auto':
        if not args.auto_settings:p.error('Auto mode requires --auto-settings JSON')
        from .routines import auto_clean_plan
        settings=read_json(args.auto_settings)
        if not isinstance(settings,dict):p.error('Invalid auto-mode settings')
        report=auto_clean_plan(scanner,settings)
        if args.apply and 'plan' in report:
            if not args.permanent:p.error('Applying auto mode requires --permanent')
            from .cleanup import Cleaner
            report=Cleaner(args.state).apply(report['plan'],permanent=True)
            import time
            settings['lastRun']=time.time();atomic_json(args.auto_settings,settings)
    elif action=='analyse':
        from .ai import AIAnalyzer
        ai=AIAnalyzer(args.state,args.agent,args.model,args.effort,custom_command=args.command)
        outcome=ai.run(scanner,args.dry_run);report=scanner.report(args.mode);report['analysis']=outcome
    elif action=='plan':
        from .cleanup import create_plan
        report=create_plan(scanner,args.mode,method=args.method)
    else:report=scanner.report(args.mode)
    if args.output:atomic_json(args.output,report)
    if args.json or action in ('analyse','plan','auto'):emit(report)
    else:
        print(f'Sōji · {args.mode.capitalize()} · ANALYSIS')
        print(f'{human(scanner.bytes)} measured · {scanner.visited:,} visited · {human(report["selectedBytes"])} proposed')
        print(f'{scanner.unreadable} unreadable · {scanner.skipped} excluded · {"PARTIAL" if report["limited"] else "complete"}')
        for f in scanner.decisions(args.mode)[:60]:print(f'{human(f.size):>10}  {"READY" if f.selected else "KEEP ":5}  {f.group:<26}  {f.path}\n                  {f.decision}')
    return 0


def ai_command(p,argv):
    from . import agent
    p.prog='soji ai'
    p.add_argument('operation',choices=['brief','inspect','propose','skill'])
    p.add_argument('targets',nargs='*',help='brief: scan roots (default home) · inspect: row id · propose: verdicts file or -')
    p.add_argument('--session',help='Session id from a briefing (default: latest)')
    p.add_argument('--mode',choices=MODES,default='balanced')
    p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=60)
    p.add_argument('--json',action='store_true',help='brief: JSON only, without the skill block')
    p.add_argument('--hide-held',action='store_true',help='brief: omit rows with holds')
    p.add_argument('--protect',action='append',default=[]);p.add_argument('--home')
    p.add_argument('--max-seconds',type=float,default=300);p.add_argument('--max-files',type=int,default=1000000);p.add_argument('--min-mb',type=float,default=10)
    p.add_argument('--recent-activity-hours',type=float,default=24,help='Recent-use protection window (default 24 h in AI mode)')
    p.add_argument('--no-index',action='store_true');p.add_argument('--output');p.add_argument('--method',choices=['trash','permanent'],default='trash')
    args=p.parse_args(argv)
    if args.operation=='skill':
        print('---\nname: soji\ndescription: Free disk space on macOS safely with Sōji. Use when the user asks to clean up disk space, caches, build output or old dependencies.\n---\n\nStart with `soji --ai [paths]` and follow the instructions it prints.\n\n'+agent.SKILL);return 0
    if args.limit<1 or args.offset<0 or args.max_files<1 or args.max_seconds<=0 or args.min_mb<0:p.error('Invalid limits')
    if not math.isfinite(args.recent_activity_hours) or args.recent_activity_hours<0:p.error('Invalid recent activity hours')
    def make(roots,home,protected,recent):
        options=dict(home=home,protected=protected,max_files=args.max_files,max_seconds=args.max_seconds,min_bytes=int(args.min_mb*1000000),recent_activity_hours=recent)
        if args.no_index:return Scanner(roots,**options)
        from .index import IndexedScanner
        return IndexedScanner(roots,database=Path(args.state)/'index.sqlite',**options)
    if args.operation=='brief':
        roots=args.targets or [str(Path.home())]
        for path in roots:
            if not Path(path).expanduser().is_dir():p.error('Not a directory: '+path)
        scanner=make(roots,args.home,args.protect+[args.state],args.recent_activity_hours);scanner.run()
        if scanner.error:raise ValueError(scanner.error)
        result=agent.brief(scanner,args.state,args.mode,args.offset,args.limit,include_held=not args.hide_held)
        if args.json:emit(result)
        else:sys.stdout.write(agent.render(result))
        return 0
    session=args.session or agent.latest_session(args.state)
    if args.operation=='inspect':
        if len(args.targets)!=1:p.error('inspect needs exactly one row id')
        emit(agent.inspect(args.state,session,args.targets[0]));return 0
    if len(args.targets)!=1:p.error('propose needs a verdicts file or -')
    raw=sys.stdin.read() if args.targets[0]=='-' else Path(args.targets[0]).read_text()
    try:value=json.loads(raw)
    except ValueError:raise ValueError('Verdicts are not valid JSON')
    factory=lambda data:make(data['roots'],data['home'],data['protected'],data['recentActivityHours'])
    emit(agent.propose(args.state,session,value,factory,output=args.output,method=args.method));return 0


def entry():
    try:return main()
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError) as e:print('soji: '+str(e),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(entry())
