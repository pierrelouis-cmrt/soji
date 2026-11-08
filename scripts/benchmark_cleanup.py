#!/usr/bin/env python3
"""Compare catalog-wide per-item verification with scoped batch cleanup.

Only creates/moves synthetic JSONL files in TemporaryDirectory. Native helpers,
process inspection and system app roots are disabled. Durable journal fsyncs stay
on. This isolates verification scaling, not real-machine subprocess latency.
Run: python3 -B scripts/benchmark_cleanup.py --sessions 400 --targets 40
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from corpus import hermetic
from soji_cli.cleanup import Cleaner,create_plan
from soji_cli.engine import Scanner


def run(sessions,targets,batched):
    with tempfile.TemporaryDirectory(prefix='soji-clean-bench-') as temporary:
        base=Path(temporary).resolve();home=base/'home';root=home/'.codex/sessions/2020/01/01'
        root.mkdir(parents=True)
        for i in range(sessions):
            path=root/f'rollout-{i:05}.jsonl';path.write_text('{}\n')
            os.utime(path,(time.time()-30*86400,)*2)
        with hermetic(str(home)):
            scan=Scanner([str(home)],home=str(home),min_bytes=0);scan.run()
            paths={f.path for f in scan.decisions('careful') if f.selected}
            paths=set(sorted(paths)[:targets]);plan=create_plan(scan,'careful',paths=paths)
            if len(plan['items'])!=targets:raise RuntimeError('Fixture eligibility differs from requested target count')
            cleaner=Cleaner(base/'state',trash_directory=base/'trash')
            visited=[0];original=Scanner.visit
            def visit(scanner,path,*args,**kwargs):
                visited[0]+=1;return original(scanner,path,*args,**kwargs)
            def whole_catalog(cleaner,scanner,path,root,hint):scanner.visit(root)
            with patch.object(Scanner,'visit',visit):
                started=time.perf_counter()
                if batched:result=cleaner.apply(plan)
                else:
                    with patch.object(Cleaner,'measure_catalog_target',whole_catalog):result=cleaner._apply(plan)
                elapsed=time.perf_counter()-started
            if result['completed']!=targets:raise RuntimeError(result)
            return {'seconds':round(elapsed,3),'visitedEntries':visited[0],'completed':result['completed']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions',type=int,default=400)
    parser.add_argument('--targets',type=int,default=40)
    args=parser.parse_args()
    if not 0<args.targets<=args.sessions:parser.error('Require 0 < targets <= sessions')
    print(json.dumps({'sessions':args.sessions,'targets':args.targets,
                      'unbatchedCatalog':run(args.sessions,args.targets,False),
                      'scopedBatch':run(args.sessions,args.targets,True)},indent=2))
