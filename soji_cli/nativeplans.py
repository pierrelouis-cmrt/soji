"""Plans for native catalogs, bound to current tool-reported identities."""
import time
import uuid
from pathlib import Path
from .catalogs import document_versions,runtime_catalog
from .cleanup import file_identity,digest
from .util import timestamp

def runtime_images(catalog):
    raw=catalog.get('images') or {}
    if isinstance(raw,dict):raw=raw.get('images',raw)
    if isinstance(raw,dict):return [dict(v,identifier=v.get('identifier',k)) for k,v in raw.items() if isinstance(v,dict)]
    return raw if isinstance(raw,list) else []

def booted_runtimes(catalog):
    raw=catalog.get('devices') or {};groups=raw.get('devices',{}) if isinstance(raw,dict) else {}
    return {rid for rid,items in groups.items() if any(d.get('state')!='Shutdown' for d in items)}

def finalize(items,roots,home,mode='aggressive'):
    plan={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),'mode':mode,'roots':roots,'home':home,'protected':[],'items':items,'method':'permanent','warnings':['Native cleanup is permanent; current documents, conflicts, active and retained runtimes are excluded.']}
    plan['digest']=digest(plan);return plan

def versions_plan(document,home):
    doc=str(Path(document).resolve());catalog=document_versions(doc)
    if not isinstance(catalog,dict) or 'versions' not in catalog:raise ValueError('Document versions unavailable: '+str(catalog))
    items=[]
    for version in catalog['versions']:
        if version['retained']:continue
        action={'kind':'document-version','document':doc,'version':version.get('unit') or version['url'],'versionModified':version['modified']}
        items.append({'path':doc,'identity':file_identity(doc),'size':0,'newest':version['modified'],'files':1,'hint':'document-versions','group':'Document versions','method':'permanent','action':action,'finding':{}})
    # Multiple actions on one document are valid; validation deduplicates actions.
    return finalize(items,[str(Path(doc).parent)],home)

def runtimes_plan(home,catalog=None):
    catalog=runtime_catalog() if catalog is None else catalog
    images=runtime_images(catalog);busy=booted_runtimes(catalog)
    if not catalog.get('available'):raise ValueError('Runtime/device service unavailable')
    newest={}
    for image in images:
        rid=image.get('runtimeIdentifier')
        if rid:
            from .specialized import version_key
            if rid not in newest or version_key(image.get('build',''))>version_key(newest[rid].get('build','')):newest[rid]=image
    items=[];roots=set()
    for image in images:
        path=image.get('path');rid=image.get('runtimeIdentifier')
        if not rid or not image.get('identifier') or not path or not Path(path).exists() or not image.get('deletable') or image.get('state') not in ('Ready','ReadyToUse','Available'):continue
        if rid in busy or newest.get(rid)==image:continue
        last=timestamp(image.get('lastUsedAt'))
        if not last or time.time()-last<7*86400:continue
        path=str(Path(path).resolve());roots.add(str(Path(path).parent))
        action={'kind':'simulator-runtime','identifier':image['identifier'],'runtimeIdentifier':rid,'build':image.get('build')}
        items.append({'path':path,'identity':file_identity(path),'size':image.get('sizeBytes',0),'newest':last,'files':1,'hint':'simulator-runtime','group':'Simulators and emulators','method':'permanent','action':action,'finding':{}})
    return finalize(items,sorted(roots),home)

def verify_native(item):
    action=item['action'];kind=action['kind']
    if kind=='document-version':
        catalog=document_versions(action['document'])
        if not isinstance(catalog,dict) or not isinstance(catalog.get('versions'),list):raise ValueError('Fresh document version catalog unavailable')
        if item['path']!=action['document']:raise ValueError('Document action does not match target')
        version=next((v for v in catalog['versions'] if (v.get('unit') or v['url'])==action['version'] or v['url']==action['version']),None)
        if not version or version.get('retained') or version.get('modified')!=action.get('versionModified'):raise ValueError('Document version is no longer removable')
    elif kind=='simulator-runtime':
        catalog=runtime_catalog()
        # Derive the current eligible plan, including active-device and retention checks.
        plan=runtimes_plan(str(Path.home()),catalog)
        if not any(i['action']==action and i['path']==item['path'] for i in plan['items']):raise ValueError('Runtime no longer passes current retention and device checks')
    else:raise ValueError('Unsupported native catalog action')

    return {'kind':kind,'action':action,'catalogVerified':True}
