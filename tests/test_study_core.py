import copy
from datetime import datetime,timedelta,timezone
import unittest
from app.study_core import chunks,retrieve,progress,fingerprint,lower_bound
NOW=datetime(2026,10,25,tzinfo=timezone.utc)
TOPICS=[{'id':'t','chapter':'3','section':'3.2','title':'Matrices','weight':1}]
def session(n=10,correct=True,difficulty=2,hinted=False,mode='practice',finished=True,age=0):
 return {'id':'s','topic_id':'t','mode':mode,'finished':finished,'questions':[{'prompt':f'Result for distinct matrix case {i}?','options':[f'A{i}',f'B{i}',f'C{i}',f'D{i}'],'difficulty':difficulty,'attempt':{'answer':0,'correct':correct,'hinted':hinted,'at':(NOW-timedelta(days=age)).isoformat()}} for i in range(n)]}
class StudyCoreTests(unittest.TestCase):
 def test_unassessed(self):
  p=progress(TOPICS,[],NOW);self.assertIsNone(p['practice_readiness']);self.assertEqual(p['readiness_level'],0)
 def test_one_answer_not_ready(self):
  p=progress(TOPICS,[session(1)],NOW);self.assertEqual(p['readiness_level'],1);self.assertLess(p['practice_readiness'],50)
 def test_hints_small_xp_no_readiness(self):
  p=progress(TOPICS,[session(hinted=True)],NOW);self.assertEqual(p['evidence_count'],0);self.assertEqual(p['xp'],20)
 def test_repeats_no_farming(self):
  s=session();self.assertEqual(progress(TOPICS,[s],NOW),progress(TOPICS,[s,copy.deepcopy(s)],NOW))
 def test_shuffled_options_same_fingerprint(self):
  q=session(1)['questions'][0];other=copy.deepcopy(q);other['options'].reverse();self.assertEqual(fingerprint(q),fingerprint(other))
 def test_distinct_math_numbers_are_not_collapsed(self):
  a={'prompt':'Evaluate 2 + 3','options':['4','5','6','7']};b={'prompt':'Evaluate 2 + 4','options':['4','5','6','7']}
  self.assertNotEqual(fingerprint(a),fingerprint(b))
 def test_old_answers_keep_xp_not_readiness(self):
  p=progress(TOPICS,[session(age=31)],NOW);self.assertEqual(p['evidence_count'],0);self.assertGreater(p['xp'],0)
 def test_unfinished_exam_no_evidence(self):
  p=progress(TOPICS,[session(mode='exam',finished=False)],NOW);self.assertEqual(p['xp'],0);self.assertEqual(p['evidence_count'],0)
 def test_disputed_excluded(self):
  s=session(1);s['questions'][0]['disputed']=True;p=progress(TOPICS,[s],NOW);self.assertEqual(p['xp'],0)
 def test_scope_edit_resets_evidence_not_xp(self):
  p=progress([{**TOPICS[0],'scope_revision':1}],[session()],NOW);self.assertEqual(p['evidence_count'],0);self.assertGreater(p['xp'],0)
 def test_weighted_untested_scope(self):
  other={'id':'x','chapter':'4','section':'4.1','title':'Limits','weight':3}
  a=progress(TOPICS,[session(20)],NOW);b=progress(TOPICS+[other],[session(20)],NOW)
  self.assertLess(b['practice_readiness'],a['practice_readiness']/2);self.assertEqual(b['coverage'],50)
 def test_no_timed_blocks_upper_level(self):self.assertLess(progress(TOPICS,[session(60,difficulty=3)],NOW)['readiness_level'],4)
 def test_mock_ready_evidence(self):self.assertEqual(progress(TOPICS,[session(30,difficulty=3,mode='exam')],NOW)['readiness_level'],4)
 def test_strong_evidence_reachable_for_single_topic(self):self.assertEqual(progress(TOPICS,[session(60,difficulty=3,mode='exam')],NOW)['readiness_level'],5)
 def test_wrong_answers_lower_score(self):self.assertGreater(progress(TOPICS,[session()],NOW)['practice_readiness'],progress(TOPICS,[session(correct=False)],NOW)['practice_readiness'])
 def test_wilson_bound(self):
  self.assertEqual(lower_bound(0,0),0);self.assertLess(lower_bound(5,5),1);self.assertGreater(lower_bound(30,30),lower_bound(5,5))
 def test_chunk_page_identity(self):
  c=chunks([{'page':7,'text':'x'*3000}]);self.assertGreater(len(c),1);self.assertTrue(all(p['page']==7 for p in c))
 def test_lexical_retrieval(self):
  p=[{'page':1,'text':'matrix eigenvalues eigenvectors'},{'page':2,'text':'integral accumulated change'}]
  self.assertEqual(retrieve(p,'eigenvalues')[0]['page'],1);self.assertEqual(retrieve(p,'unfindable'),[])
 def test_arabic_retrieval(self):self.assertEqual(retrieve([{'page':3,'text':'المصفوفة والقيم الذاتية'}],'الذاتية')[0]['page'],3)
if __name__=='__main__':unittest.main()
