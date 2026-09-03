from src.evaluator import run_gate1_replay

def test_gate1_replay():
    results = {r['fixture']: r for r in run_gate1_replay()}
    assert all(results[k]['pass'] for k in ['PISTA','ONADA','OCHO','LESSON'])
    pista = results['PISTA']['events'][0]
    assert pista['status'] == 'VERIFIED'
    assert (pista['date'],pista['start_time'],pista['end_time'],pista['fee']) == ('2026-08-22','19:00','23:00',13000)
    onada = results['ONADA']['events'][0]
    assert onada['status'] == 'POSSIBLE'
    assert onada['start_time'] == '21:00' and onada['end_time'] == '02:00' and onada['end_day_offset'] == 1
    assert len(results['OCHO']['events']) == 8
    assert len(results['LESSON']['events']) == 0
