"""Live release transport smoke check. Reads only public code, never a user's vault."""
import hashlib,json,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.update_engine import get_public,verify_manifest,extract_release
root=Path(__file__).resolve().parent.parent
cfg=json.loads((root/'publisher.json').read_text())
if not cfg.get('manifest_url'):raise SystemExit('No release publisher configured')
last=None
for attempt in range(3):
 try:
  manifest=verify_manifest(json.loads(get_public(cfg['manifest_url'],65536)),cfg['public_key'])
  raw=get_public(manifest['url'],manifest['size'])
  assert len(raw)==manifest['size'] and hashlib.sha256(raw).hexdigest()==manifest['sha256'],'Archive checksum mismatch'
  with tempfile.TemporaryDirectory() as temp:extract_release(raw,Path(temp)/'release',manifest['version'])
  print('Live publisher verified: signed manifest, archive checksum and safe extraction for version',manifest['version']);break
 except Exception as exc:
  last=exc
  if attempt==2:raise
  time.sleep(3)
