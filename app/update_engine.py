"""Signed, staged source releases. User data and code have separate lifecycles."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_RELEASE = 30*1024*1024


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):
        raise ValueError('Release version must use major.minor.patch.')
    return tuple(map(int,value.split('.')))


def canonical(manifest):
    return json.dumps({k:v for k,v in manifest.items() if k!='signature'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def verify_manifest(manifest,public_key):
    fields={'version','data_schema','url','sha256','size','signature'}
    if not isinstance(manifest,dict) or set(manifest)!=fields: raise ValueError('Invalid release manifest fields.')
    version(manifest['version'])
    if manifest['data_schema']!=1: raise ValueError('This release uses an incompatible data schema. Your current app is unchanged.')
    if type(manifest['size']) is not int or not 1<=manifest['size']<=MAX_RELEASE: raise ValueError('Release size is outside the allowed limit.')
    if not isinstance(manifest['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',manifest['sha256']): raise ValueError('Invalid release checksum.')
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key,validate=True)).verify(base64.b64decode(manifest['signature'],validate=True),canonical(manifest))
    except Exception:
        raise ValueError('Release signature is invalid. No update was installed.') from None
    return manifest


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    with open(temporary,'w',encoding='utf-8') as handle:
        json.dump(value,handle);handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)


def read_json(path,default):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (ValueError,OSError): return default


def get_public(url,limit):
    # No proxy, cookies, machine-local URLs or authenticated redirects.
    from .browser_core import normalize_public_url, resolve_public_addresses, _PinnedHTTPSConnection
    url=normalize_public_url(url)
    parsed=urlsplit(url)
    connection=_PinnedHTTPSConnection(parsed.hostname,resolve_public_addresses(parsed.hostname)[0],30)
    try:
        target=parsed.path or '/'
        if parsed.query: target+='?'+parsed.query
        connection.request('GET',target,headers={'User-Agent':'SultanLocalAI-Updater/1','Accept-Encoding':'identity','Connection':'close'})
        response=connection.getresponse()
        if response.status!=200: raise ValueError(f'Update server returned HTTP {response.status}. Use a direct public HTTPS feed/archive URL.')
        if (response.getheader('Content-Encoding') or 'identity').lower()!='identity': raise ValueError('Compressed HTTP update responses are unsupported.')
        data=response.read(limit+1)
        if len(data)>limit: raise ValueError('Update download exceeded its size limit.')
        return data
    finally: connection.close()


def extract_release(raw,directory,expected_version):
    directory=Path(directory)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist())>500: raise ValueError('Too many files in release.')
        total,seen=0,set()
        entries=[]
        for info in archive.infolist():
            name=info.filename
            if '\\' in name or ':' in name or '\x00' in name or name.startswith('/'): raise ValueError('Unsafe archive path.')
            parts=PurePosixPath(name).parts
            if parts and parts[0]=='sultan-local-ai': parts=parts[1:]
            if not parts: continue
            reserved={'con','prn','aux','nul'}|{f'com{i}' for i in range(1,10)}|{f'lpt{i}' for i in range(1,10)}
            if any(p.rstrip(' .')!=p or p.split('.')[0].casefold() in reserved or any(c in p for c in '<>"|?*') for p in parts):
                raise ValueError('Unsafe Windows archive path.')
            if any(p in ('..','.venv','.git','models','backups','updates','__pycache__') or p.startswith('.') for p in parts):
                # Explicit metadata files are harmless, but private/runtime content never belongs in releases.
                if len(parts)==1 and parts[0]=='.gitignore': continue
                raise ValueError('Release contains private/runtime paths.')
            if info.is_dir(): continue
            if (info.external_attr>>16)&0o170000 == 0o120000: raise ValueError('Symlinks are not allowed in releases.')
            rel=Path(*parts)
            if parts[0] not in ('app','scripts','tests') and len(parts)>1: raise ValueError('Unexpected release directory.')
            if len(parts)==1 and parts[0] not in ('run.py','version.json','requirements.txt','requirements-speech.txt','requirements-dev.txt','LICENSE','README.md','INTEGRATIONS.md','START-HERE.txt','VERIFICATION.md','STUDY-GUIDE.md','ARCHITECTURE.md','publisher.json','Start-Windows.cmd','SETUP-EVERYTHING.cmd','Setup-Local-Model-Windows.cmd','Install-Speech-Windows.cmd','Check-Windows.cmd'):
                raise ValueError('Unexpected top-level release file.')
            if any(p.endswith(('.sqlite3','.pem','.key')) for p in parts) or parts[-1] in ('setup-defaults.json','.env'): raise ValueError('Private data must never be in a release.')
            folded=str(rel).casefold()
            if folded in seen: raise ValueError('Duplicate release path.')
            seen.add(folded)
            total+=info.file_size
            if total>60*1024*1024 or info.file_size>10*1024*1024: raise ValueError('Release expands beyond its limit.')
            entries.append((info,rel))
        if not {'run.py','version.json','requirements.txt','app/main.py'}.issubset(seen): raise ValueError('Release is missing essential files.')
        version_info=json.loads(archive.read(next(info for info,rel in entries if str(rel)=='version.json')))
        if version_info!={'version':expected_version,'data_schema':1}: raise ValueError('Archive version does not match its signed manifest.')
        directory.mkdir(parents=True,exist_ok=False)
        try:
            for info,rel in entries:
                path=directory/rel;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(archive.read(info))
        except Exception:
            shutil.rmtree(directory,ignore_errors=True);raise


class UpdateManager:
    def __init__(self,data_root,app_root):
        self.data=Path(data_root);self.app=Path(app_root)
        self.root=self.data/'updates';self.root.mkdir(parents=True,exist_ok=True)
        self.bootstrap_version=read_json(self.app/'version.json',{'version':'0.2.0'})['version']
        active=read_json(self.root/'active.json',{}) or {}
        self.current_version=max((self.bootstrap_version,active.get('version',self.bootstrap_version)),key=version)

    def config(self):
        # Publisher trust is shipped with app code, never learned from a downloaded manifest.
        return read_json(self.app/'publisher.json',{})

    def status(self):
        cfg=self.config();prefs=read_json(self.root/'preferences.json',{})
        return {'version':self.current_version,'configured':bool(cfg.get('manifest_url') and cfg.get('public_key')),
                'automatic':prefs.get('automatic',False),'pending':read_json(self.root/'pending.json',None),
                'active':read_json(self.root/'active.json',None),'last_check':read_json(self.root/'last-check.json',None),
                'message':'Updates need a hosted release feed and pinned signing key. Your vault stays outside the app folder.'}

    def preferences(self,automatic):
        if automatic and not self.status()['configured']: raise ValueError('Automatic releases are not connected yet. A repository and trusted release feed must be set up first.')
        atomic_json(self.root/'preferences.json',{'automatic':bool(automatic)})
        return self.status()

    def check(self):
        cfg=self.config()
        if not self.status()['configured']: raise ValueError('No trusted release feed is configured. Nothing was downloaded.')
        manifest=verify_manifest(json.loads(get_public(cfg['manifest_url'],65536)),cfg['public_key'])
        if version(manifest['version'])<=version(self.current_version):
            atomic_json(self.root/'last-check.json',{'at':datetime.now(timezone.utc).isoformat(),'result':'up_to_date'})
            return {'update_available':False}
        raw=get_public(manifest['url'],manifest['size'])
        if len(raw)!=manifest['size'] or hashlib.sha256(raw).hexdigest()!=manifest['sha256']: raise ValueError('Release checksum or size mismatch. Current app is unchanged.')
        target=self.root/'versions'/manifest['version']
        target.parent.mkdir(parents=True,exist_ok=True)
        # Keep a valid already-staged version; each release version is immutable.
        if not target.exists(): extract_release(raw,target,manifest['version'])
        atomic_json(self.root/'pending.json',{'version':manifest['version'],'sha256':manifest['sha256']})
        atomic_json(self.root/'last-check.json',{'at':datetime.now(timezone.utc).isoformat(),'result':'staged','version':manifest['version']})
        return {'update_available':True,'version':manifest['version'],'message':'Verified release staged. Close and reopen the app to install it with a backup and rollback protection.'}

    def activate_pending(self):
        pending=read_json(self.root/'pending.json',None)
        if not pending: return
        release=version(pending['version'])
        if release<=version(self.current_version): (self.root/'pending.json').unlink(missing_ok=True);return
        target=self.root/'versions'/pending['version']
        if read_json(target/'version.json',{})!={'version':pending['version'],'data_schema':1}: raise ValueError('Staged release is incomplete.')
        executable=target/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not executable.exists(): subprocess.run([sys.executable,'-m','venv',str(target/'.venv')],check=True)
        requirement='requirements-speech.txt' if __import__('importlib.util',fromlist=['find_spec']).find_spec('faster_whisper') else 'requirements.txt'
        subprocess.run([str(executable),'-m','pip','install','-r',str(target/requirement)],cwd=target,check=True)
        with tempfile.TemporaryDirectory(prefix='sultan-release-check-') as scratch:
            env={**os.environ,'SULTAN_DATA_DIR':scratch}
            subprocess.run([str(executable),'-c','from app.main import app; assert app.state.vault.initialized is False'],cwd=target,env=env,check=True,timeout=60)
        # Backup before the new process can open the user's vault.
        database=self.data/'vault.sqlite3'
        if database.exists():
            backup=self.data/'backups';backup.mkdir(exist_ok=True)
            dest=backup/('before-update-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.sqlite3')
            source=sqlite3.connect(database);destination=sqlite3.connect(dest)
            try: source.backup(destination)
            finally: destination.close();source.close()
            os.chmod(dest,0o600)
        old=read_json(self.root/'active.json',None)
        atomic_json(self.root/'previous.json',old)
        atomic_json(self.root/'active.json',{'version':pending['version']})
        (self.root/'pending.json').unlink(missing_ok=True)

    def target(self):
        active=read_json(self.root/'active.json',None)
        if not active or version(active['version'])<=version(self.bootstrap_version): return None
        target=self.root/'versions'/active['version']
        if not target.is_dir(): raise ValueError('The active update is missing. Use rollback to return to the original app.')
        return target

    def rollback(self):
        previous=read_json(self.root/'previous.json',None)
        atomic_json(self.root/'active.json',previous)
        (self.root/'previous.json').unlink(missing_ok=True)
        (self.root/'pending.json').unlink(missing_ok=True)
        return {'message':'Previous code selected for next restart. Personal data was not changed.'}
