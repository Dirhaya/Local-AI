import base64,hashlib,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from app.update_engine import verify_manifest,canonical,extract_release,UpdateManager,atomic_json

def archive(v='0.3.0',extra=None):
 data=io.BytesIO()
 with zipfile.ZipFile(data,'w') as z:
  for name,text in {'run.py':'print("test")','version.json':json.dumps({'version':v,'data_schema':1}),'requirements.txt':'','app/main.py':'app = None',**(extra or {})}.items():z.writestr('sultan-local-ai/'+name,text)
 return data.getvalue()
class UpdateTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.app=self.root/'app';self.app.mkdir();atomic_json(self.app/'version.json',{'version':'0.2.0','data_schema':1})
  self.key=Ed25519PrivateKey.generate();self.public=base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
 def tearDown(self):self.temp.cleanup()
 def manifest(self,raw):
  m={'version':'0.3.0','data_schema':1,'url':'https://example.com/release.zip','sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)};m['signature']=base64.b64encode(self.key.sign(canonical(m))).decode();return m
 def test_signature_and_tamper(self):
  m=self.manifest(archive());self.assertEqual(verify_manifest(m,self.public),m);m['version']='0.4.0'
  with self.assertRaisesRegex(ValueError,'signature'):verify_manifest(m,self.public)
 def test_wrong_key(self):
  other=base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
  with self.assertRaises(ValueError):verify_manifest(self.manifest(archive()),other)
 def test_future_schema(self):
  m=self.manifest(archive());m['data_schema']=2
  with self.assertRaisesRegex(ValueError,'schema'):verify_manifest(m,self.public)
 def test_safe_extract(self):
  p=self.root/'release';extract_release(archive(),p,'0.3.0');self.assertTrue((p/'app/main.py').is_file())
 def test_reject_unsafe_paths_before_writing(self):
  for name in ['../escape.py','.venv/python.exe','app/../../vault.sqlite3','vault.sqlite3','setup-defaults.json','app/secret.key','app/.. /escape.py','app/CON.txt','app/file.py.']:
   with self.subTest(name=name):
    with self.assertRaises(ValueError):extract_release(archive(extra={name:'bad'}),self.root/'bad','0.3.0')
    self.assertFalse((self.root/'bad').exists())
 def test_archive_manifest_mismatch(self):
  with self.assertRaises(ValueError):extract_release(archive('0.9.0'),self.root/'bad','0.3.0')
 def test_unconfigured_no_network(self):
  m=UpdateManager(self.root/'data',self.app);self.assertFalse(m.status()['configured'])
  with patch('app.update_engine.get_public',side_effect=AssertionError('no network')):
   with self.assertRaises(ValueError):m.check()
  with self.assertRaises(ValueError):m.preferences(True)
 def test_stage_preserves_vault(self):
  raw=archive();m=self.manifest(raw);atomic_json(self.app/'publisher.json',{'manifest_url':'https://example.com/feed.json','public_key':self.public})
  data=self.root/'data';data.mkdir();(data/'vault.sqlite3').write_bytes(b'private-data-sentinel');manager=UpdateManager(data,self.app)
  with patch('app.update_engine.get_public',side_effect=[json.dumps(m).encode(),raw]):self.assertTrue(manager.check()['update_available'])
  self.assertEqual((data/'vault.sqlite3').read_bytes(),b'private-data-sentinel');self.assertTrue((data/'updates/versions/0.3.0/run.py').exists())
 def test_checksum_mismatch(self):
  m=self.manifest(archive());atomic_json(self.app/'publisher.json',{'manifest_url':'https://example.com/feed','public_key':self.public});manager=UpdateManager(self.root/'data',self.app)
  with patch('app.update_engine.get_public',side_effect=[json.dumps(m).encode(),b'bad']):
   with self.assertRaises(ValueError):manager.check()
  self.assertIsNone(manager.status()['pending'])
 def test_rollback_preserves_data(self):
  data=self.root/'data';data.mkdir();(data/'vault.sqlite3').write_bytes(b'encrypted');m=UpdateManager(data,self.app);atomic_json(m.root/'active.json',{'version':'0.3.0'});m.rollback()
  self.assertEqual((data/'vault.sqlite3').read_bytes(),b'encrypted');self.assertIsNone(m.target())
 def test_failed_dependency_install_does_not_activate(self):
  m=UpdateManager(self.root/'data',self.app);target=m.root/'versions/0.3.0';target.parent.mkdir(parents=True);extract_release(archive(),target,'0.3.0');atomic_json(m.root/'pending.json',{'version':'0.3.0'})
  with patch('app.update_engine.subprocess.run',side_effect=RuntimeError('pip failed')):
   with self.assertRaises(RuntimeError):m.activate_pending()
  self.assertFalse((m.root/'active.json').exists())
if __name__=='__main__':unittest.main()
