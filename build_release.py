#!/usr/bin/env python3
"""Build the native helper, the portable zipapp and the release files.

dist/ then holds everything a GitHub release needs (soji.pyz, soji.pyz.sha256,
Soji-VERSION.zip, install.sh) plus soji.rb for the Homebrew tap."""
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import tempfile
import zipapp
import zipfile
BASE=Path(__file__).resolve().parent
OUT=BASE/'dist';OUT.mkdir(exist_ok=True)
VERSION=re.search(r"__version__ = '([^']+)'",(BASE/'soji_cli/__init__.py').read_text()).group(1)
REPO='pierrelouis-cmrt/soji'
with tempfile.TemporaryDirectory(prefix='soji-release-') as tmp:
    temp=Path(tmp)
    binaries=[]
    for arch in ('arm64','x86_64'):
        binary=temp/('soji-native-'+arch)
        subprocess.run(['swiftc','-O','-target',arch+'-apple-macosx13.0','-module-cache-path',str(temp/'swift-cache'),str(BASE/'native/SojiNative.swift'),'-o',str(binary)],check=True)
        binaries.append(binary)
    helper=BASE/'soji_cli/native-bin/soji-native';helper.parent.mkdir(exist_ok=True)
    subprocess.run(['/usr/bin/lipo','-create',*map(str,binaries),'-output',str(helper)],check=True)
    helper.chmod(0o755)
    stage=temp/'Soji';stage.mkdir()
    for name in ['soji_cli','tests','native','scripts']:
        shutil.copytree(BASE/name,stage/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','integration-*','tmp*'))
    for name in ['soji','Launch Sōji.command','entrypoint.py','install.sh','README.md','build_release.py','NEXT_STEPS.md']:
        shutil.copy2(BASE/name,stage/name)
    payload=temp/'payload';payload.mkdir();shutil.copytree(stage/'soji_cli',payload/'soji_cli')
    (payload/'__main__.py').write_text('from soji_cli.__main__ import entry\nraise SystemExit(entry())\n')
    zipapp.create_archive(payload,stage/'soji.pyz',interpreter='/usr/bin/env python3',compressed=True)
    shutil.copy2(stage/'soji.pyz',OUT/'soji.pyz')
    archive=OUT/f'Soji-{VERSION}.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in stage.rglob('*'):
            if p.is_file():z.write(p,Path('Soji')/p.relative_to(stage))
    shutil.copy2(archive,OUT/'Soji.zip')
pyz=OUT/'soji.pyz'
digest=hashlib.sha256(pyz.read_bytes()).hexdigest()
(OUT/'soji.pyz.sha256').write_text(digest+'  soji.pyz\n')
shutil.copy2(BASE/'install.sh',OUT/'install.sh')
formula=(BASE/'packaging/homebrew/soji.rb').read_text()
formula=formula.split('class Soji',1)[1]
formula='class Soji'+formula.replace('@VERSION@',VERSION).replace('@SHA256@',digest).replace('@REPO@',REPO)
(OUT/'soji.rb').write_text(formula)
for name in (archive.name,'soji.pyz','soji.pyz.sha256','install.sh','soji.rb'):print(OUT/name)
