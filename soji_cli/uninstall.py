"""Explicit third-party app uninstall plans with attributable user-library leftovers.
No system app removal, administrator escalation, or unbounded receipt deletion.

Attribution sources: bundle ID/name paths, plus Group Containers named by the
app's signed application-group entitlements or prefixed by its Team ID.
Leftovers attributable to another installed app, Apple-owned groups, or files
recorded by a different user-domain pkg receipt are listed as shared and never
removed. Execution re-derives the same attribution and refuses on any change.
"""
from pathlib import Path
import time
import uuid
from . import apps as appmod
from .apps import AppCatalog,apple_group
from .cleanup import file_identity,digest
from .util import inside


def _plain(p,h):
    return p.exists() and not p.is_symlink() and str(p.resolve())==str(p) and inside(str(p),str(h))


def attributed_paths(app,home):
    h=Path(home).resolve();bundle=app['bundle'];name=app['name'];paths=[]
    for token in (bundle,name):
        if not token or token in ('.','..') or '/' in token or '\x00' in token:
            raise ValueError('App attribution requires safe bundle and name components')
    for rel in ['Library/Application Support/'+name,'Library/Application Support/'+bundle,'Library/Caches/'+bundle,'Library/Containers/'+bundle,'Library/Preferences/'+bundle+'.plist','Library/Saved Application State/'+bundle+'.savedState']:
        p=h/rel
        if _plain(p,h):paths.append(str(p))
    return sorted(set(paths))


def _pkg_belongs(pkg,bundle):
    p=pkg.casefold();b=bundle.casefold()
    return bool(b) and (p==b or p.startswith(b+'.'))


def leftovers(app,home,cat,receipts=None):
    """Return (removable, shared) for `app`.
    removable: [{'path','reason'}]; shared: [{'path','reason','owners'}]."""
    h=Path(home).resolve()
    candidates=[(p,'bundle-or-name') for p in attributed_paths(app,home)]
    ident=cat.identity(app);gc=h/'Library/Group Containers'
    names=set(ident['groups'])
    if ident['team'] and gc.is_dir():
        try:names|={e.name for e in gc.iterdir() if e.name.startswith(ident['team']+'.')}
        except OSError:pass
    for name in sorted(names):
        if not appmod.safe_component(name):continue
        p=gc/name
        if _plain(p,h):candidates.append((str(p),'group-entitlement' if name in ident['groups'] else 'team-prefix'))
    if receipts is None:receipts=appmod.user_receipts(h)
    removable=[];shared=[]
    for path,reason in candidates:
        name=Path(path).name
        if reason!='bundle-or-name' and apple_group(name):
            shared.append({'path':path,'reason':'apple-group','owners':['Apple']});continue
        owners=list(cat.owner(path))
        if reason!='bundle-or-name':owners+=cat.group_owners(name)
        others=sorted({a['bundle'] or a['path'] for a in owners if a['path']!=app['path']})
        if others:shared.append({'path':path,'reason':'shared-app-owner','owners':others});continue
        pkgs=sorted(pkg for pkg,files in receipts.items() if not _pkg_belongs(pkg,app['bundle']) and any(inside(f,path) for f in files))
        if pkgs:shared.append({'path':path,'reason':'pkg-receipt','owners':pkgs});continue
        removable.append({'path':path,'reason':reason})
    return removable,shared


def uninstall_plan(target,home):
    cat=AppCatalog(home).build()
    app=next((a for a in cat.apps if target in (a['path'],a['bundle'],a['name'])),None)
    if not app:raise ValueError('Installed application not found')
    if app['bundle'].startswith('com.apple.') or app['path'].startswith('/System/'):raise ValueError('System/Apple apps cannot be uninstalled')
    if not cat.running_available:raise ValueError('Running-app inventory unavailable; uninstall refused')
    if cat.is_running(app):raise ValueError('Quit the app before creating an uninstall plan')
    removable,shared=leftovers(app,home,cat)
    ident=cat.identity(app)
    items=[]
    for entry in removable+[{'path':app['path'],'reason':'app-bundle'}]:
        path=entry['path']
        items.append({'path':path,'identity':file_identity(path),'size':0,'newest':0,'files':0,'hint':'explicit-uninstall','group':'Applications' if path==app['path'] else 'App leftovers','method':'trash','action':{'kind':'uninstall','app':app,'appIdentity':file_identity(app['path']),'codeIdentity':ident,'attribution':entry['reason']},'finding':{}})
    warnings=['Explicit uninstall includes app data at the listed paths. Every item goes to Trash; review before applying.']
    if shared:warnings.append(f'{len(shared)} leftover(s) are shared with another owner (app, Apple or package receipt) and are listed but not removed.')
    plan={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),'mode':'careful','roots':[str(Path(home)),str(Path(app['path']).parent)],'home':str(Path(home).resolve()),'protected':[],'items':items,'shared':shared,'method':'trash','warnings':warnings}
    plan['digest']=digest(plan);return plan


def verify_uninstall(item,home):
    action=item['action'];app=action['app'];cat=AppCatalog(home).build()
    current=next((a for a in cat.apps if a['path']==app['path'] and a['bundle']==app['bundle']),None)
    if current is None or current!=app:raise ValueError('App identity no longer present; recreate uninstall plan')
    if current['bundle'].startswith('com.apple.') or current['path'].startswith('/System/'):raise ValueError('System application')
    expected=action.get('appIdentity')
    if expected is None or file_identity(current['path'])!=expected:raise ValueError('Application identity changed; recreate uninstall plan')
    if not cat.running_available:raise ValueError('Running-app inventory unavailable; uninstall refused')
    if cat.is_running(current):raise ValueError('App is running')
    if item['path']==current['path']:return {'app':current,'runningAvailable':True,'running':False,'identityVerified':True}
    reason=action.get('attribution','bundle-or-name')
    if reason!='bundle-or-name' and 'codeIdentity' not in action:raise ValueError('Signing attribution missing; recreate uninstall plan')
    if 'codeIdentity' in action and cat.identity(current)!=action['codeIdentity']:raise ValueError('Signing identity changed; recreate uninstall plan')
    removable,shared=leftovers(current,home,cat)
    if any(s['path']==item['path'] for s in shared):raise ValueError('Leftover is now shared with another owner; recreate uninstall plan')
    if not any(r['path']==item['path'] and r['reason']==reason for r in removable):raise ValueError('Leftover no longer attributable to this app')

    return {'app':current,'runningAvailable':True,'running':False,'identityVerified':True,'attribution':reason}
