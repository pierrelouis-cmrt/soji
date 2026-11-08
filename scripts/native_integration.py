"""Opt-in native integration check. Writes only disposable fixture state.
No model call, no personal cleanup. Run from the source tree on macOS.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from soji_cli.index import IndexedScanner
from soji_cli.ai import AIAnalyzer
from soji_cli.platform import native

base=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='integration-',dir=base/'tests') as raw:
    root=Path(raw).resolve();home=root/'home';home.mkdir();(home/'data').mkdir();(home/'data/file').write_text('original')
    state=root/'state'
    first=IndexedScanner([str(home)],home=str(home),database=state/'index.sqlite',context=False,min_bytes=0);first.run()
    assert not first.error,first.error
    second=IndexedScanner([str(home)],home=str(home),database=state/'index.sqlite',context=False,min_bytes=0);second.run()
    assert not second.error,second.error
    assert second.index_info['strategy']=='incremental',second.index_info
    (home/'data/file').write_text('updated payload'*1000)
    third=IndexedScanner([str(home)],home=str(home),database=state/'index.sqlite',context=False,min_bytes=0);third.run()
    assert not third.error,third.error
    assert third.nodes[str(home/'data/file')].apparent==15000
    fourth=IndexedScanner([str(home)],home=str(home),database=state/'index.sqlite',context=False,min_bytes=0);fourth.run()
    assert not fourth.error,fourth.error
    assert fourth.index_info['reusedEntries']>0,fourth.index_info
    fake=root/'agent.py'
    fake.write_text('''import json,os,pathlib,subprocess
run=pathlib.Path(os.environ['SOJI_RUN_DIR'])
for protected in ['index.sqlite','index.sqlite-wal','report.json','sandbox.sb']:
 try:
  with (run/protected).open('ab') as f:f.write(b'forbidden')
  raise AssertionError('Sandbox allowed protected write: '+protected)
 except PermissionError:pass
cfg=json.loads((run/'soji-mcp.json').read_text())['mcpServers']['soji']
p=subprocess.Popen([cfg['command'],*cfg['args']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,**cfg['env']))
for i,(method,params) in enumerate([('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'fixture','version':'1'}}),('tools/call',{'name':'disk_summary','arguments':{}}),('tools/call',{'name':'submit_findings','arguments':{'findings':[]}})],1):
 p.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\\n');p.stdin.flush()
 response=json.loads(p.stdout.readline())
 assert 'error' not in response,response
 assert not response.get('result',{}).get('isError'),response
p.stdin.close();p.wait(timeout=5)
print('Fixture agent completed without contacting any model')
''')
    analyzer=AIAnalyzer(state,preset='custom',custom_command=[sys.executable,str(fake)])
    result=analyzer.run(third)
    assert result['executed'] and result['submitted']==0,result
    assert (Path(result['runDirectory'])/'submission.json').exists()
    print(json.dumps({'nativeEventID':native('event-id'),'first':first.index_info,'second':second.index_info,'third':third.index_info,'fourth':fourth.index_info,'fakeAgent':result,'networkModelCalls':0},indent=2))
