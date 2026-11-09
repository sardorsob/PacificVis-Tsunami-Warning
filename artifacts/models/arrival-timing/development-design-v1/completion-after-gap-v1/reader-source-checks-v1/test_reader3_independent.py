"""Bounded independent Reader3 metadata probes on synthetic roots only."""
import json
import pytest
from analysis.arrival import model_development_completion_report as r
from analysis.arrival.evidence import write_json, sha256
from tests.test_arrival_model_development_completion_report import complete_fixture, future_gap_fixture


def reject_before_rows(root, monkeypatch):
    monkeypatch.setattr(r, 'read_rows', lambda *a: pytest.fail('metadata failed to close before table parse'))
    with pytest.raises(ValueError):
        r.report(root, root/'unpublished')
    assert not (root/'unpublished').exists()


def test_complete_shape_preserves_six_checks_and_c1_null_scores(tmp_path, monkeypatch):
    complete_fixture(tmp_path, monkeypatch)
    r.report(tmp_path, tmp_path/'published')
    s=json.loads((tmp_path/'published/summary.json').read_text())
    assert sum(len(v['checks']) for v in s['lanes']) == 6
    assert s['lanes'][0]['checks'][0]['aggregate']['equal_event_score'] == -.25
    assert s['lanes'][0]['checks'][1]['aggregate'] is None
    assert s['lanes'][0]['checks'][1]['aggregate_without_crossing_event'] is None
    assert len(s['numerical_check_gaps']) == 1


@pytest.mark.parametrize('fault', ['unknown_leaf','empty_directory','symlink_leaf'])
def test_resealed_physical_tail_does_not_become_producer_output(tmp_path, monkeypatch, fault):
    seal=complete_fixture(tmp_path, monkeypatch)
    s=json.loads((tmp_path/r.SUMMARIES['check']).read_text())
    folder,_=r.fit.case_paths(tmp_path,s['jobs'][0])
    p=folder/'unlisted'
    if fault == 'unknown_leaf': p.write_text('retained unknown bytes')
    elif fault == 'empty_directory': p.mkdir()
    else: p.symlink_to(folder/'result.json')
    seal()
    reject_before_rows(tmp_path, monkeypatch)
    assert p.exists()


@pytest.mark.parametrize('phase',r.PHASES)
def test_resealed_allocation_cannot_switch_original_job(tmp_path, monkeypatch, phase):
    seal=complete_fixture(tmp_path, monkeypatch)
    s=json.loads((tmp_path/r.SUMMARIES[phase]).read_text())
    record=s['attempt_records'][0]
    path=tmp_path/record['allocation']
    a=json.loads(path.read_text())
    a['job']['order'] += 1
    write_json(path,a)
    receipt=tmp_path/record['receipt']
    body=json.loads(receipt.read_text());body['allocation_sha256']=sha256(path)
    write_json(receipt,body)
    folder,_=(r.recovery if phase == 'full_design_recovery' else r.fit).case_paths(tmp_path,s['jobs'][0])
    process=folder.with_name(folder.name+'.supervisor.json')
    supervisor=json.loads(process.read_text());supervisor['allocation_sha256']=sha256(path)
    write_json(process,supervisor)
    seal()
    reject_before_rows(tmp_path, monkeypatch)


@pytest.mark.parametrize('fault', ['new_gap_aggregate','cross_phase_disposition','missing_full_attempt'])
def test_later_gap_cannot_relax_other_admissions(tmp_path, monkeypatch, fault):
    seal,job,review,disposition=future_gap_fixture(tmp_path,monkeypatch)
    if fault == 'new_gap_aggregate':
        p=tmp_path/review
        v=json.loads(p.read_text());v['primary_aggregate_available']=True
        write_json(p,v)
        dp=tmp_path/disposition
        d=json.loads(dp.read_text());d['review_sha256']=sha256(p)
        write_json(dp,d)
        for summary_path in r.SUMMARIES.values():
            sp=tmp_path/summary_path
            sv=json.loads(sp.read_text())
            sv['logical_check_dispositions'][-1].update(review_sha256=sha256(p),disposition_sha256=sha256(dp))
            write_json(sp,sv)
    else:
        p=tmp_path/r.SUMMARIES['full_development']
        v=json.loads(p.read_text())
        if fault == 'cross_phase_disposition':
            v['logical_check_dispositions'][-1]['job']['order'] += 1
        else: v['attempt_records'].pop()
        write_json(p,v)
    if fault != 'missing_full_attempt':
        seal()
    else:
        for path in [r.data.CHECK_REVIEW, r.old.SMOKE_REVIEW, r.GATE]:
            value=json.loads((tmp_path/path).read_text())
            value['files']={n:sha256(tmp_path/n) for n in value['files']}
            write_json(tmp_path/path,value)
    reject_before_rows(tmp_path,monkeypatch)
