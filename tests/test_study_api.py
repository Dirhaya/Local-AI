from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def study_client(tmp_path):
 with TestClient(create_app(tmp_path),base_url='http://127.0.0.1:8765',headers={'X-Local-AI':'1'}) as c:
  assert c.post('/api/setup',json={'passphrase':'correct horse battery staple'}).status_code==200
  course=c.post('/api/study/courses',json={'title':'Linear algebra'}).json()
  with patch('app.study.parse_pdf',return_value={'pages':[{'page':1,'text':'Eigenvalues are scalars satisfying Av = lambda v for nonzero vectors.'}],'warning':'Check notation.'}):
   doc=c.post('/api/study/documents',data={'course_id':course['id']},files={'file':('notes.pdf',b'%PDF-placeholder','application/pdf')}).json()
  topic=c.post('/api/study/topics',json={'course_id':course['id'],'chapter':'3','section':'3.2','title':'Eigenvalues','document_ids':[doc['id']]}).json()
  yield c,course,doc,topic

def generated():
 return {'questions':[{'prompt':'Which condition defines an eigenvalue of A?','options':['Av = lambda v for nonzero v','Av = 0 for every v','All entries equal lambda','A must be the zero matrix'],'correct':0,'explanation':'Use the nonzero-vector relation in the supplied passage.','citation_ids':['S1']}]}

def new_session(c,topic,mode='practice'):
 with patch('app.study.json_reply',return_value=generated()):
  r=c.post('/api/study/practice',json={'topic_id':topic['id'],'count':1,'mode':mode})
 assert r.status_code==200,r.text
 return r.json()

def test_answers_hidden_and_first_answer_cannot_be_replaced(study_client):
 c,course,doc,topic=study_client;s=new_session(c,topic)
 assert 'correct' not in s['questions'][0] and 'explanation' not in s['questions'][0]
 key=c.app.state.vault.get('study_session',s['id'])['questions'][0]['correct']
 r=c.post('/api/study/practice/'+s['id']+'/answer',json={'index':0,'answer':key})
 assert r.json()['questions'][0]['attempt']['correct']
 assert c.post('/api/study/practice/'+s['id']+'/answer',json={'index':0,'answer':0}).status_code==409

def test_hint_marks_attempt_assisted(study_client):
 c,course,doc,topic=study_client;s=new_session(c,topic)
 assert c.post('/api/study/practice/'+s['id']+'/hint',json={'index':0}).status_code==200
 c.post('/api/study/practice/'+s['id']+'/answer',json={'index':0,'answer':0})
 assert c.get('/api/study/progress',params={'course_id':course['id']}).json()['evidence_count']==0

def test_timed_solutions_hidden_until_finish(study_client):
 c,course,doc,topic=study_client;s=new_session(c,topic,'exam')
 assert c.post('/api/study/practice/'+s['id']+'/hint',json={'index':0}).status_code==400
 r=c.post('/api/study/practice/'+s['id']+'/answer',json={'index':0,'answer':0})
 assert 'correct' not in r.json()['questions'][0]
 assert c.get('/api/study/progress',params={'course_id':course['id']}).json()['evidence_count']==0
 r=c.post('/api/study/practice/'+s['id']+'/finish')
 assert 'correct' in r.json()['questions'][0]

def test_unmatched_question_does_not_call_model(study_client):
 c,course,doc,topic=study_client
 with patch('app.study.json_reply',side_effect=AssertionError('No model for absent passage')):
  r=c.post('/api/study/ask',json={'topic_id':topic['id'],'question':'unfindablexyz'})
 assert r.status_code==200 and r.json()['sources']==[]

def test_invalid_citations_rejected(study_client):
 c,course,doc,topic=study_client
 with patch('app.study.json_reply',return_value={'answer':'unsupported','citation_ids':['S999']}):
  r=c.post('/api/study/ask',json={'topic_id':topic['id'],'question':'Explain eigenvalues'})
 assert r.status_code==503

def test_pdf_and_progress_are_vault_content_not_plain_files(study_client):
 c,course,doc,topic=study_client
 vault=c.app.state.vault
 assert b'Eigenvalues are scalars' not in vault.path.read_bytes()
 assert c.get('/api/study/documents/'+doc['id']+'/pages/1').json()['page']==1
 assert c.delete('/api/study/documents/'+doc['id']).status_code==200
 assert c.get('/api/study/documents/'+doc['id']+'/pages/1').status_code==404
