"""Real browser/API/PDF flow with a deterministic local Ollama fixture (not an AI quality test)."""
import io,json,os,re,subprocess,sys,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject

class OllamaFixture(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send_json(self,data):
  raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):self.send_json({'models':[{'name':'test-local:latest','size':1024}]})
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
  if self.path=='/api/show':return self.send_json({'model_info':{'fixture':True}})
  if 'Create multiple-choice' in body['messages'][0]['content']:
   request=json.loads(body['messages'][1]['content'])
   data={'questions':[{'prompt':f'Which definition identifies eigenvalues in case {i+1}?','options':['Nonzero vector Av = lambda v','All vectors must be zero','Every matrix entry is the same','The matrix must be rectangular'],'correct':0,'explanation':'The definition requires a nonzero eigenvector satisfying Av = lambda v.','citation_ids':['S1']} for i in range(request['count'])]}
  else:data={'answer':'An eigenvalue satisfies Av = lambda v for a nonzero vector.','citation_ids':['S1']}
  self.send_json({'message':{'content':json.dumps(data)}})

def make_pdf(path):
 w=PdfWriter();p=w.add_blank_page(width=600,height=800)
 font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
 p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
 stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 700 Td (Eigenvalues are scalars satisfying Av = lambda v for nonzero vectors. Chapter 3 section 3.2.) Tj ET')
 p[NameObject('/Contents')]=w._add_object(stream)
 with open(path,'wb') as f:w.write(f)

@pytest.fixture
def local_app(tmp_path):
 fixture=ThreadingHTTPServer(('127.0.0.1',0),OllamaFixture);threading.Thread(target=fixture.serve_forever,daemon=True).start()
 env={**os.environ,'SULTAN_DATA_DIR':str(tmp_path/'vault'),'SULTAN_OLLAMA_URL':f'http://127.0.0.1:{fixture.server_port}','SULTAN_DEFAULT_MODEL':'test-local:latest'}
 process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765','--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 try:
  for _ in range(100):
   if process.poll() is not None:raise RuntimeError(process.stderr.read().decode())
   try:
    with urllib.request.urlopen('http://127.0.0.1:8765/api/status',timeout=1):break
   except OSError:time.sleep(.1)
  else:raise RuntimeError('App startup timed out')
  yield tmp_path
 finally:
  process.terminate();process.wait(timeout=10);fixture.shutdown();fixture.server_close()

def test_pdf_question_practice_progress_and_unlock(local_app):
 with sync_playwright() as pw:
  browser=pw.chromium.launch()
  page=browser.new_page(viewport={'width':1366,'height':900})
  page.set_default_timeout(15000)
  errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto('http://127.0.0.1:8765')
  page.locator('#passphrase').fill('correct horse battery staple');page.locator('#passphrase-confirm').fill('correct horse battery staple');page.locator('#gate-submit').click()
  page.locator('#add-course').click();page.locator('#course-title').fill('Linear algebra');page.locator('#course-form button[type=submit]').click()
  page.get_by_role('button',name='Your PDFs',exact=True).click()
  source=local_app/'notes.pdf';make_pdf(source);page.locator('#study-upload').set_input_files(str(source))
  page.locator('.document-card').filter(has_text='notes.pdf').wait_for()
  page.locator('#add-topic').click();page.locator('#topic-chapter').fill('3');page.locator('#topic-section').fill('3.2');page.locator('#topic-title').fill('Eigenvalues');page.locator('#topic-end').fill('1');page.locator('#topic-form button[type=submit]').click()
  page.locator('.study-context').filter(has_text='Section 3.2').wait_for()
  page.get_by_role('button',name='Ask your PDFs',exact=True).click();page.locator('#study-question').fill('Explain eigenvalues');page.locator('#study-ask-form button[type=submit]').click()
  page.locator('#study-answer-result').get_by_text('An eigenvalue satisfies',exact=False).wait_for()
  assert 'PDF page 1' in page.locator('#study-answer-result').inner_text()
  page.get_by_role('button',name='Practice & quests',exact=True).click();page.locator('#practice-count').select_option('3');page.locator('#practice-difficulty').select_option('1');page.locator('#practice-form button[type=submit]').click()
  page.get_by_role('heading',name='Question 1 of 3',exact=True).wait_for()
  assert page.locator('.answer-correct').count()==0
  page.locator('.answer-option').filter(has_text='Nonzero vector Av').click();page.locator('#answer-form button[type=submit]').click()
  page.locator('.notice.good').filter(has_text='Correct.').wait_for()
  page.locator('#next-question').click();page.locator('#question-hint').click();page.locator('.notice').filter(has_text='now assisted').wait_for()
  page.locator('.answer-option').filter(has_text='Nonzero vector Av').click();page.locator('#answer-form button[type=submit]').click()
  page.on('dialog',lambda dialog:dialog.accept());page.locator('#finish-session').click()
  page.get_by_text('Session complete · review the evidence',exact=True).wait_for()
  assert '16 XP' in page.locator('.study-stats').inner_text()
  page.locator('#lock-button').click();page.locator('#gate').wait_for(state='visible')
  assert page.locator('#content').inner_text()==''
  page.locator('#passphrase').fill('correct horse battery staple');page.locator('#gate-submit').click()
  page.locator('.study-context').filter(has_text='Section 3.2').wait_for()
  assert '16 XP' in page.locator('.study-stats').inner_text()
  assert not errors,errors
  browser.close()
