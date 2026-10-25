"""Deterministic retrieval and transparent, versioned practice scoring. No network."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re

SCORING_VERSION = 1
STOP = set('a an and are as at be by for from how i in is it of on or that the this to was what when where which with explain please'.split())


def tokens(text):
    return [t for t in re.findall(r"[^\W_]+", text.lower(), re.UNICODE) if t not in STOP and len(t) > 1]


def chunks(pages, size=1300, overlap=150):
    result = []
    for page in pages:
        text = page['text']
        for start in range(0, len(text), size - overlap):
            part = text[start:start + size].strip()
            if part:
                result.append({'page': page['page'], 'text': part, 'offset': start})
    return result


def retrieve(passages, query, count=8):
    terms = set(tokens(query))
    if not terms:
        return []
    bags = [Counter(tokens(p['text'])) for p in passages]
    length = sum(sum(b.values()) for b in bags) / max(1, len(bags))
    frequencies = Counter(term for bag in bags for term in bag)
    ranked = []
    for index, (p, bag) in enumerate(zip(passages, bags)):
        score = 0.0
        for term in terms:
            tf = bag[term]
            if tf:
                idf = math.log(1 + (len(bags) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(bag.values()) / max(1, length)))
        if score:
            ranked.append((score, -index, p))
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [p for _, _, p in ranked[:count]]


def fingerprint(question):
    # Option shuffling must not make an old question count as fresh evidence.
    normalize = lambda value: ' '.join(re.findall(r'[^\W_]+|[=+*/^<>-]',value.casefold(),re.UNICODE))
    normalized = normalize(question['prompt']) + '|' + '|'.join(sorted(normalize(o) for o in question['options']))
    return hashlib.sha256(normalized.encode()).hexdigest()


def lower_bound(correct, total):
    if not total:
        return 0.0
    # 80% Wilson lower confidence bound; a conservative practice statistic, not a validated exam predictor.
    z = 1.2815515655
    p = correct / total
    return max(0.0, (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) / (1+z*z/total))


def progress(topics, sessions, at=None):
    at = at or datetime.now(timezone.utc)
    cutoff = at - timedelta(days=30)
    all_evidence = []
    revisions = {t['id']:t.get('scope_revision',0) for t in topics}
    for session in sessions:
        if session.get('mode') == 'exam' and not session.get('finished'):
            continue
        for q in session.get('questions', []):
            if q.get('disputed'):
                continue
            attempt = q.get('attempt')
            if attempt:
                all_evidence.append((attempt['at'], session, q, attempt))
    all_evidence.sort(key=lambda item: item[0])
    seen, records, xp = set(), [], 0
    for _, session, question, attempt in all_evidence:
        key = (session['topic_id'], fingerprint(question))
        if key in seen:
            continue
        seen.add(key)
        assisted = attempt.get('hinted', False) or attempt.get('revealed', False)
        xp += 2 if assisted else 4 + ((6, 12, 20)[question['difficulty']-1] if attempt['correct'] else 0)
        timestamp = datetime.fromisoformat(attempt['at'])
        if timestamp >= cutoff and not assisted and session.get('scope_revision',0)==revisions.get(session['topic_id']):
            records.append((session, question, attempt))
    summaries = []
    for topic in topics:
        evidence = [(s, q, a) for s, q, a in records if s['topic_id'] == topic['id']][-30:]
        n = len(evidence)
        correct = sum(a['correct'] for _, _, a in evidence)
        hard = sum(q['difficulty'] == 3 for _, q, _ in evidence)
        timed = sum(s.get('mode') == 'exam' for s, _, _ in evidence)
        score = round(100 * lower_bound(correct, n))
        needs = []
        if n < 5: needs.append(f'{5-n} more independent questions for initial evidence')
        if hard < 2: needs.append(f'{2-hard} more exam-level questions')
        if timed < 2: needs.append(f'{2-timed} more questions in a timed session')
        summaries.append({'topic_id':topic['id'], 'chapter':topic['chapter'], 'section':topic['section'],
                          'title':topic['title'], 'weight':topic.get('weight',1), 'attempts':n,
                          'correct':correct, 'hard_attempts':hard, 'timed_attempts':timed,
                          'score':score, 'evidence':'insufficient' if n < 5 else 'initial' if n < 15 else 'established',
                          'next_steps':needs or ['Practise missed concepts and recheck after a delay.']})
    total_weight = sum(t['weight'] for t in summaries)
    score = round(sum(t['score']*t['weight'] for t in summaries)/total_weight) if total_weight else 0
    coverage = sum(t['attempts'] >= 5 for t in summaries) / len(summaries) if summaries else 0
    n = len(records)
    hard = sum(t['hard_attempts'] for t in summaries)
    timed = sum(t['timed_attempts'] for t in summaries)
    level, label = 0, 'Unassessed'
    if n: level, label = 1, 'Learning'
    if n >= 8 and score >= 40 and coverage >= .5: level, label = 2, 'Building skill'
    if n >= 20 and score >= 60 and coverage >= .8 and hard >= 4: level, label = 3, 'Exam practice'
    if n >= 30 and score >= 75 and coverage == 1 and hard >= 6 and timed >= 6: level, label = 4, 'Ready for a mock'
    if n >= 50 and score >= 85 and coverage == 1 and hard >= 12 and timed >= 12: level, label = 5, 'Strong practice evidence'
    return {'scoring_version':SCORING_VERSION, 'readiness_level':level, 'readiness_label':label,
            'practice_readiness':score if n else None, 'evidence_count':n, 'coverage':round(coverage*100),
            'xp':xp, 'player_level':1+math.isqrt(xp//50), 'next_level_xp':50*(math.isqrt(xp//50)+1)**2,
            'topics':summaries, 'evidence_window_days':30,
            'meaning':'Practice estimate over your configured sections, not a predicted exam grade. Difficulty and answer keys are AI-generated; inspect disputed questions. Repeated identical questions and hinted/revealed answers do not increase readiness.'}
