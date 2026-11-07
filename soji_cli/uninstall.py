"""Explicit third-party app uninstall plans with attributable user-library leftovers.
No system app removal, administrator escalation, or unbounded receipt deletion.
"""
from pathlib import Path
import os
import time
import uuid
from .apps import AppCatalog
from .cleanup import file_identity,digest
from .util import inside


def attributed_paths(app,home):
    h=Path(home).resolve();bundle=app['bundle'];name=app['name'];paths=[]
    for token in (bundle,name):
        if not token or token in ('.','..') or '/' in token or '\x00' in token:
            raise ValueError('App attribution requires safe bundle and name components')
    for rel in ['Library/Application Support/'+name,'Library/Application Support/'+bundle,'Library/Caches/'+bundle,'Library/Containers/'+bundle,'Library/Preferences/'+bundle+'.plist','Library/Saved Application State/'+bundle+'.savedState']:
        p=h/rel
        if p.exists() and not p.is_symlink() and str(p.resolve())==str(p) and inside(str(p),str(h)):
            paths.append(str(p))
    return sorted(set(paths))


def uninstall_plan(target,home):
    cat=AppCatalog(home).build()
    app=next((a for a in cat.apps if target in (a['path'],a['bundle'],a['name'])),None)
    if not app:raise ValueError('Installed application not found')
    if app['bundle'].startswith('com.apple.') or app['path'].startswith('/System/'):raise ValueError('System/Apple apps cannot be uninstalled')
    if cat.is_running(app):raise ValueError('Quit the app before creating an uninstall plan')
    paths=attributed_paths(app,home)+[app['path']]
    items=[]
    for path in paths:
        items.append({'path':path,'identity':file_identity(path),'size':0,'newest':0,'files':0,'hint':'explicit-uninstall','group':'Applications' if path==app['path'] else 'App leftovers','method':'trash','action':{'kind':'uninstall','app':app,'appIdentity':file_identity(app['path'])},'finding':{}})
    plan={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),'mode':'careful','roots':[str(Path(home)),str(Path(app['path']).parent)],'home':str(Path(home).resolve()),'protected':[],'items':items,'method':'trash','warnings':['Explicit uninstall includes app data at the listed paths. Every item goes to Trash; review before applying.']}
    plan['digest']=digest(plan);return plan


def verify_uninstall(item,home):
    app=item['action']['app'];cat=AppCatalog(home).build()
    current=next((a for a in cat.apps if a['path']==app['path'] and a['bundle']==app['bundle']),None)
    if current is None or current!=app:raise ValueError('App identity no longer present; recreate uninstall plan')
    if current['bundle'].startswith('com.apple.') or current['path'].startswith('/System/'):raise ValueError('System application')
    expected=item['action'].get('appIdentity')
    if expected is None or file_identity(current['path'])!=expected:raise ValueError('Application identity changed; recreate uninstall plan')
    if cat.is_running(current):raise ValueError('App is running')
    if item['path'] not in attributed_paths(current,home)+[current['path']]:raise ValueError('Leftover no longer attributable to this app')
