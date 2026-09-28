"""Behavioral checks for research authority, hostile evidence and deterministic replay."""
import json

import pytest

from james_library.services.experiment_protocol.bundle import save_experiment_bundle, verify_bundle_integrity
from james_library.services.experiment_protocol.fixtures import run_positive_control_fixture
from james_library.services.experiment_protocol.ingestion import ingest_result
from james_library.services.experiment_protocol.manifest import calculate_sha256, canonical_json_str
from james_library.services.experiment_protocol.research import (
    create_plan, execute_plan, inspect_record, main, validate_plan,
)


@pytest.fixture
def evidence():
    manifest, result, analysis = run_positive_control_fixture()
    data = result.pop('_embedded_data')
    return manifest, result, data, analysis


def run(plan, tmp_path, approval=None):
    return execute_plan(plan, approved_sha256=approval, operator='R.A.I.N.Operator',
                        code_revision='a' * 40, base_dir=tmp_path)


def test_missing_authorization_never_calls_executor(monkeypatch, tmp_path):
    def prohibited(*args, **kwargs):
        pytest.fail('Execution occurred without approval')
    monkeypatch.setattr('james_library.services.experiment_protocol.research.SimulatedCircleExecutor', prohibited)
    with pytest.raises(ValueError, match='approval'):
        run(create_plan(), tmp_path)
    assert not list(tmp_path.iterdir())


def test_changed_plan_invalidates_approval(tmp_path):
    plan = create_plan()
    digest = validate_plan(plan)
    plan['scenario']['active_effect'] = -100
    with pytest.raises(ValueError, match='approval'):
        run(plan, tmp_path, digest)


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(schema_version='2.0.0'),
    lambda p: p.update(human_authorization={'status': 'GRANTED'}),
    lambda p: p['scenario'].update(sample_count=True),
    lambda p: p['scenario'].update(sample_count=10001),
    lambda p: p['scenario'].update(noise_std=-1),
    lambda p: p['scenario'].update(active_effect=float('nan')),
    lambda p: p['scenario'].update(command='run arbitrary code'),
    lambda p: p['manifest'].update(protocol_version='2.0.0'),
    lambda p: p['manifest'].update(experiment_id='../escape'),
    lambda p: p['manifest']['preregistered_analysis'].update(alpha_threshold=0),
    lambda p: p['proposal'].update(origin='Jev'),
    lambda p: p['proposal'].update(confidence=1.0, authorized=True),
    lambda p: p.update(seed=19),
])
def test_approval_cannot_override_failed_checks(tmp_path, mutation):
    plan = create_plan()
    mutation(plan)
    with pytest.raises(ValueError):
        run(plan, tmp_path, calculate_sha256(plan))
    assert not list(tmp_path.iterdir())


def test_observation_wins_and_replay_preserves_evidence(tmp_path):
    plan = create_plan()
    bundle = run(plan, tmp_path, validate_plan(plan))
    before = {p: p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    report = inspect_record(bundle)
    assert report['predicted_difference_ohms'] == -20
    assert -17 < report['observed_difference_ohms'] < -15
    assert report['observed_difference_ohms'] != report['predicted_difference_ohms']
    assert report['reproduced_measurements'] is True
    assert report['authorization']['status'] == 'GRANTED'
    assert report['limitations']
    assert before == {p: p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        run(plan, tmp_path, validate_plan(plan))
    assert before == {p: p.read_bytes() for p in bundle.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(protocol_version='9.0.0'),
    lambda r: r.update(provenance='RAW_MEASURED'),
    lambda r: r.update(provenance='MODEL_INFERRED'),
    lambda r: r.update(executor_type='REPLAY'),
    lambda r: r.update(manifest_sha256='0' * 64),
    lambda r: r.update(trial_id='TRL-00000000'),
    lambda r: r.update(execution_id='EXEC-00000000'),
    lambda r: r.update(started_at='not a date'),
    lambda r: r.update(ended_at='1900-01-01T00:00:00+00:00'),
    lambda r: r.update(human_authorization=True),
    lambda r: r.pop('software_version'),
    lambda r: r.update(checksums={}),
    lambda r: r.update(raw_artifact_references=[]),
])
def test_external_result_rejected(evidence, mutation):
    manifest, result, data, _ = evidence
    mutation(result)
    with pytest.raises(ValueError):
        ingest_result(manifest, result, data)


@pytest.mark.parametrize('bad', [None, {}, [], {'measurements': {}}, 'not an object'])
def test_malformed_measurements_rejected(evidence, bad):
    manifest, result, _, _ = evidence
    with pytest.raises(ValueError):
        ingest_result(manifest, result, bad)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '1'])
def test_invalid_measurement_even_with_recomputed_hash_rejected(evidence, value):
    manifest, result, data, _ = evidence
    data['measurements']['active'][0] = value
    digest = calculate_sha256(canonical_json_str(data))
    result['raw_artifact_references'][0]['sha256'] = digest
    result['checksums'] = {result['raw_artifact_references'][0]['path']: digest}
    with pytest.raises(ValueError):
        ingest_result(manifest, result, data)


def test_ingress_returns_isolated_payload_and_never_opens_artifact_path(evidence):
    manifest, result, data, _ = evidence
    result['raw_artifact_references'][0]['path'] = 'https://example.invalid/not-fetched'
    result['checksums'] = {'https://example.invalid/not-fetched': result['raw_artifact_references'][0]['sha256']}
    accepted = ingest_result(manifest, result, data)
    data['measurements']['active'][0] = 900
    assert accepted['_embedded_data']['measurements']['active'][0] != 900
    assert '_embedded_data' not in result


@pytest.mark.parametrize('inventory', [{}, [], None, {'../outside': '0' * 64}])
def test_incomplete_inventory_rejected(tmp_path, inventory):
    (tmp_path / 'checksums.json').write_text(json.dumps(inventory))
    assert not verify_bundle_integrity(tmp_path)['valid']


@pytest.mark.parametrize('path', ['../outside', '/etc/passwd', 'data/../../outside', 'C:\\outside', './result.json'])
def test_unsafe_inventory_paths_rejected(tmp_path, path):
    manifest, result, analysis = run_positive_control_fixture()
    bundle = save_experiment_bundle(tmp_path, manifest, result, analysis)
    checksums = json.loads((bundle / 'checksums.json').read_text())
    checksums[path] = '0' * 64
    (bundle / 'checksums.json').write_text(json.dumps(checksums))
    assert not verify_bundle_integrity(bundle)['valid']


def test_bundle_rejects_symlinks_and_untracked_files(tmp_path):
    manifest, result, analysis = run_positive_control_fixture()
    bundle = save_experiment_bundle(tmp_path, manifest, result, analysis)
    extra = bundle / 'extra.json'
    extra.write_text('{}')
    assert not verify_bundle_integrity(bundle)['valid']
    extra.unlink()
    extra.symlink_to(tmp_path / 'outside')
    assert not verify_bundle_integrity(bundle)['valid']


def test_bundle_id_cannot_escape_output(tmp_path):
    manifest, result, analysis = run_positive_control_fixture()
    manifest['experiment_id'] = '../../outside'
    with pytest.raises(ValueError):
        save_experiment_bundle(tmp_path, manifest, result, analysis)


def test_reanalysis_detects_modified_observations_even_if_inventory_rehashed(tmp_path):
    plan = create_plan()
    bundle = run(plan, tmp_path, validate_plan(plan))
    record = json.loads((bundle / 'research.json').read_text())
    record['observation']['difference_ohms'] = -20
    (bundle / 'research.json').write_text(json.dumps(record))
    checksums = json.loads((bundle / 'checksums.json').read_text())
    checksums['research.json'] = calculate_sha256((bundle / 'research.json').read_bytes())
    (bundle / 'checksums.json').write_text(json.dumps(checksums))
    with pytest.raises(ValueError, match='Observation'):
        inspect_record(bundle)


def test_cli_plan_never_runs_and_does_not_overwrite(tmp_path):
    path = tmp_path / 'plan.json'
    assert main(['plan', str(path)]) == 0
    original = path.read_bytes()
    assert main(['plan', str(path)]) == 1
    assert path.read_bytes() == original
    assert main(['run', str(path), '--approve', '0'*64, '--code-revision', 'a'*40]) == 1
    assert not (tmp_path / 'experiments').exists()


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(schema_version='2.0.0'),
    lambda r: r.update(limitations=[]),
    lambda r: r.update(claim_id='unrelated'),
    lambda r: r.update(human_authorization=None),
    lambda r: r['human_authorization'].update(status='DENIED'),
    lambda r: r['human_authorization'].update(at='2100-01-01T00:00:00+00:00'),
    lambda r: r.update(validation={'status': 'FAILED'}),
    lambda r: r['reproducibility'].update(code_revision='unknown'),
    lambda r: r['reproducibility'].update(seed=100),
    lambda r: r['interpretation'].update(conclusion='PROVEN'),
])
def test_record_inspection_rejects_invalid_metadata_after_rehash(tmp_path, mutation):
    plan = create_plan()
    bundle = run(plan, tmp_path, validate_plan(plan))
    path = bundle / 'research.json'
    record = json.loads(path.read_text())
    mutation(record)
    path.write_text(json.dumps(record))
    inventory = json.loads((bundle / 'checksums.json').read_text())
    inventory['research.json'] = calculate_sha256(path.read_bytes())
    (bundle / 'checksums.json').write_text(json.dumps(inventory))
    with pytest.raises(ValueError):
        inspect_record(bundle)


def test_ingress_rejects_false_embedded_provenance_after_rehash(evidence):
    manifest, result, data, _ = evidence
    data['circle_session_header']['provenance'] = 'RAW_MEASURED'
    digest = calculate_sha256(canonical_json_str(data))
    result['raw_artifact_references'][0]['sha256'] = digest
    result['checksums'] = {result['raw_artifact_references'][0]['path']: digest}
    with pytest.raises(ValueError, match='lineage'):
        ingest_result(manifest, result, data)
