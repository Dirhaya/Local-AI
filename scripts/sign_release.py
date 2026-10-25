"""Publisher-side signing. The private key must stay outside the repository and client bundle."""
import argparse,base64,hashlib,json,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.update_engine import canonical

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 gen=sub.add_parser('keygen');gen.add_argument('--private-key',type=Path,required=True)
 sign=sub.add_parser('sign');sign.add_argument('--private-key',type=Path,required=True);sign.add_argument('--archive',type=Path,required=True);sign.add_argument('--url',required=True);sign.add_argument('--output',type=Path,required=True)
 a=p.parse_args()
 if a.command=='keygen':
  key=Ed25519PrivateKey.generate();a.private_key.parent.mkdir(parents=True,exist_ok=True)
  with open(a.private_key,'xb') as f:f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
  os.chmod(a.private_key,0o600)
  print('Pin this PUBLIC key in publisher.json:',base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode());return
 key=serialization.load_pem_private_key(a.private_key.read_bytes(),password=None)
 if not isinstance(key,Ed25519PrivateKey):raise SystemExit('Expected an Ed25519 private key.')
 from zipfile import ZipFile
 with ZipFile(a.archive) as z:info=json.loads(z.read('sultan-local-ai/version.json'))
 raw=a.archive.read_bytes();m={'version':info['version'],'data_schema':info['data_schema'],'url':a.url,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
 m['signature']=base64.b64encode(key.sign(canonical(m))).decode();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(m,indent=2),encoding='utf-8')
 print('Signed manifest written. Publish the manifest and archive at direct public HTTPS URLs; never publish the private key.')
if __name__=='__main__':main()
