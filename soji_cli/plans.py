"""Shared wire-compatible cleanup plan envelope and resource identities."""
import time
import uuid
from . import __version__
from .identity import digest


def resource_identity(item):
    action=item.get('action') or {}
    if action.get('kind')=='document-version':
        return ('document-version',action['document'],action['version'])
    return (action.get('kind','filesystem'),item['path'])


def build_plan(*,items,roots,home,mode,method,protected=(),warnings=(),**metadata):
    value={'format':'soji-clean-plan/1','id':uuid.uuid4().hex,'createdAt':time.time(),
           'mode':mode,'roots':list(roots),'home':home,'protected':list(protected),
           'items':items,'method':method,'version':__version__,'warnings':list(warnings),**metadata}
    value['digest']=digest(value)
    return value
