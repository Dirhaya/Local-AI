import threading
from pathlib import Path
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .deps import get_vault
from .update_engine import UpdateManager

router=APIRouter(prefix='/api/updates')
_lock=threading.Lock()


class Preference(BaseModel):
    automatic: bool


def manager(v):
    # The original bootstrap retains the publisher trust and active-version pointers.
    import os
    return UpdateManager(v.directory,Path(os.environ.get('SULTAN_BOOTSTRAP_ROOT',Path(__file__).parent.parent)))


@router.get('/status')
def status(v=Depends(get_vault)):
    result=manager(v).status()
    import json
    result['running_version']=json.loads((Path(__file__).parent.parent/'version.json').read_text())['version']
    return result


@router.patch('/preferences')
def preferences(body: Preference,v=Depends(get_vault)):
    return manager(v).preferences(body.automatic)


@router.post('/check')
def check(v=Depends(get_vault)):
    if not _lock.acquire(blocking=False): raise ValueError('An update check is already running.')
    try: return manager(v).check()
    finally: _lock.release()


@router.post('/backup')
def backup(v=Depends(get_vault)):
    path=v.encrypted_backup()
    return {'saved':True,'filename':path.name,'message':'Encrypted backup saved in your laptop data folder. Keep the passphrase separately.'}


@router.post('/rollback')
def rollback(v=Depends(get_vault)):
    return manager(v).rollback()
