"""Comprehensive test suite for RAIN <-> CIRCLE Experiment Protocol."""

import shutil
import tempfile
import unittest
from pathlib import Path

from james_library.services.experiment_protocol import (
    CIRCLE_PROVENANCE_VALUES,
    PhysicalCircleExecutor,
    SimulatedCircleExecutor,
    calculate_sha256,
    canonical_json_bytes,
    compute_cohens_d,
    compute_confidence_interval,
    compute_mean,
    compute_p_value_two_sample,
    compute_std_dev,
    compute_variance,
    design_experiment,
    enforce_executor_provenance,
    generate_experiment_id,
    generate_trial_id,
    run_artifact_only_fixture,
    run_deterministic_analysis,
    run_insufficient_sample_fixture,
    run_negative_control_fixture,
    run_positive_control_fixture,
    run_protocol_modification_fixture,
    save_experiment_bundle,
    validate_manifest,
    validate_record_provenance_lineage,
    verify_bundle_integrity,
    verify_manifest_hash,
)
from james_library.services.experiment_protocol.cli import run_experiment_workflow


class TestManifestContracts(unittest.TestCase):
    def test_experiment_id_generation(self):
        eid = generate_experiment_id()
        self.assertTrue(eid.startswith("EXP-"))
        self.assertGreaterEqual(len(eid), 12)

    def test_trial_id_generation_is_opaque(self):
        tid = generate_trial_id()
        self.assertTrue(tid.startswith("TRL-"))
        self.assertNotIn("ACTIVE", tid)
        self.assertNotIn("CONTROL", tid)
        self.assertNotIn("SHAM", tid)

    def test_deterministic_serialization(self):
        obj1 = {"b": 2, "a": 1, "nested": {"z": 26, "y": 25}}
        obj2 = {"nested": {"y": 25, "z": 26}, "a": 1, "b": 2}
        self.assertEqual(canonical_json_bytes(obj1), canonical_json_bytes(obj2))
        self.assertEqual(calculate_sha256(obj1), calculate_sha256(obj2))

    def test_valid_manifest_design(self):
        manifest = design_experiment(
            research_question="Does 40Hz acoustic stimulation alter baseline impedance?",
            hypothesis="40Hz stimulation induces a >= 5% impedance decrease relative to sham.",
            frequency_hz=40.0,
            min_sample_size=20,
        )
        errors = validate_manifest(manifest)
        self.assertEqual(errors, [])
        self.assertTrue(manifest["requires_human_review"])

    def test_invalid_manifest_rejection(self):
        manifest = design_experiment("Q", "H")
        del manifest["preregistered_analysis"]
        errors = validate_manifest(manifest)
        self.assertTrue(any("preregistered_analysis" in e for e in errors))

    def test_manifest_immutability_verification(self):
        manifest = design_experiment("Q", "H")
        sha = calculate_sha256(manifest)
        self.assertTrue(verify_manifest_hash(manifest, sha))

        # Tampered manifest
        tampered = dict(manifest)
        tampered["hypothesis"] = "Changed after registration"
        self.assertFalse(verify_manifest_hash(tampered, sha))


class TestProvenanceEpistemics(unittest.TestCase):
    def test_circle_provenance_vocabulary_alignment(self):
        expected = ("RAW_MEASURED", "DERIVED", "MODEL_INFERRED", "SIMULATED", "TEST", "INTERVENTION")
        self.assertEqual(CIRCLE_PROVENANCE_VALUES, expected)

    def test_simulated_executor_cannot_emit_raw_measured(self):
        with self.assertRaises(ValueError) as ctx:
            enforce_executor_provenance("SIMULATED", "RAW_MEASURED")
        self.assertIn("Epistemic violation", str(ctx.exception))

    def test_simulated_executor_allows_simulated(self):
        enforce_executor_provenance("SIMULATED", "SIMULATED")
        enforce_executor_provenance("SIMULATED", "TEST")

    def test_model_inferred_requires_lineage(self):
        record = {"provenance": "MODEL_INFERRED"}
        with self.assertRaises(ValueError):
            validate_record_provenance_lineage(record)

        valid_record = {
            "provenance": "MODEL_INFERRED",
            "source_stream_ids": ["STREAM_0"],
            "source_sequence_ranges": [{"stream_id": "STREAM_0", "first_sequence": 0, "last_sequence": 10}],
            "model": {"name": "TestModel", "version": "1.0"},
        }
        validate_record_provenance_lineage(valid_record)


class TestExecutorSafety(unittest.TestCase):
    def test_physical_executor_is_strictly_disabled(self):
        phys = PhysicalCircleExecutor()
        manifest = design_experiment("Q", "H")
        sha = calculate_sha256(manifest)
        with self.assertRaises(RuntimeError) as ctx:
            phys.prepare_experiment(manifest)
        self.assertIn("DISABLED in V1", str(ctx.exception))

        with self.assertRaises(RuntimeError) as ctx:
            phys.run_trial(manifest, sha)
        self.assertIn("SAFETY INTERLOCK", str(ctx.exception))

    def test_simulated_executor_runs_seeded(self):
        executor1 = SimulatedCircleExecutor(seed=42)
        executor2 = SimulatedCircleExecutor(seed=42)
        manifest = design_experiment("Q", "H")
        sha = calculate_sha256(manifest)

        res1 = executor1.run_trial(manifest, sha)
        res2 = executor2.run_trial(manifest, sha)

        self.assertEqual(res1["provenance"], "SIMULATED")
        self.assertEqual(res1["_embedded_data"]["measurements"], res2["_embedded_data"]["measurements"])


class TestDeterministicStatistics(unittest.TestCase):
    def test_mean_and_variance(self):
        data = [10.0, 20.0, 30.0]
        self.assertAlmostEqual(compute_mean(data), 20.0)
        self.assertAlmostEqual(compute_variance(data, ddof=1), 100.0)
        self.assertAlmostEqual(compute_std_dev(data, ddof=1), 10.0)

    def test_cohens_d(self):
        g1 = [10.0, 11.0, 10.5, 9.5]
        g2 = [15.0, 16.0, 15.5, 14.5]
        d = compute_cohens_d(g1, g2)
        self.assertGreater(d, 5.0)

    def test_p_value_two_sample(self):
        g1 = [10.0, 10.2, 9.8, 10.1, 9.9]
        g2 = [20.0, 20.2, 19.8, 20.1, 19.9]
        t_stat, p_val, df = compute_p_value_two_sample(g1, g2)
        self.assertGreater(abs(t_stat), 10.0)
        self.assertLess(p_val, 0.001)

    def test_confidence_interval(self):
        lower, upper = compute_confidence_interval(10.0, 1.0, 0.95)
        self.assertAlmostEqual(lower, 8.04, places=1)
        self.assertAlmostEqual(upper, 11.96, places=1)


class TestConclusionSemanticsAndArtifacts(unittest.TestCase):
    def test_positive_control_fixture_supports(self):
        manifest, result, analysis = run_positive_control_fixture(seed=201)
        self.assertEqual(analysis["conclusion"], "SUPPORTS")
        self.assertFalse(analysis["artifact_analysis"]["phantom_signal_detected"])
        self.assertNotIn("proven", analysis["evidence_summary"].lower())

    def test_negative_control_fixture_refutes_or_inconclusive(self):
        manifest, result, analysis = run_negative_control_fixture(seed=202)
        self.assertIn(analysis["conclusion"], ("REFUTES", "INCONCLUSIVE"))
        if analysis["conclusion"] == "REFUTES":
            self.assertTrue(analysis["falsification_criteria_met"])

    def test_artifact_only_fixture_detected_and_inconclusive(self):
        manifest, result, analysis = run_artifact_only_fixture(seed=203)
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertTrue(analysis["artifact_analysis"]["phantom_signal_detected"])
        self.assertIn("POTENTIAL_INSTRUMENTATION_ARTIFACT", analysis["artifact_analysis"]["artifact_flags"])

    def test_insufficient_sample_fixture_inconclusive(self):
        manifest, result, analysis = run_insufficient_sample_fixture(seed=204)
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertIn("Inadequate sample size", analysis["evidence_summary"])

    def test_protocol_modification_fixture_changed(self):
        manifest, result, analysis = run_protocol_modification_fixture(seed=205)
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertEqual(analysis["protocol_status"], "PROTOCOL_CHANGED")

    def test_failed_sensor_yields_inconclusive(self):
        manifest = design_experiment("Q", "H")
        sha = calculate_sha256(manifest)
        executor = SimulatedCircleExecutor(seed=42)
        scenario = {
            "sample_count": 30,
            "baseline_mean": 100.0,
            "active_effect": 8.0,
            "sensor_failed": True,
        }
        result = executor.run_trial(manifest, sha, custom_scenario=scenario)
        stats = run_deterministic_analysis(manifest, result, sha)
        self.assertEqual(stats["conclusion"], "INCONCLUSIVE")
        self.assertIn("SENSOR_DROPOUT_DETECTED", stats["quality_assessment"]["quality_flags"])


class TestBundleAndVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rain_circle_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_bundle_creation_and_integrity_check(self):
        manifest, result, analysis = run_positive_control_fixture(seed=301)
        bundle_path = save_experiment_bundle(self.temp_dir, manifest, result, analysis, logs=["Log line 1"])

        self.assertTrue((bundle_path / "manifest.json").exists())
        self.assertTrue((bundle_path / "manifest.sha256").exists())
        self.assertTrue((bundle_path / "result.json").exists())
        self.assertTrue((bundle_path / "analysis.json").exists())
        self.assertTrue((bundle_path / "provenance.json").exists())
        self.assertTrue((bundle_path / "checksums.json").exists())

        res = verify_bundle_integrity(bundle_path)
        self.assertTrue(res["valid"])
        self.assertEqual(res["mismatches"], [])

    def test_bundle_tamper_detection(self):
        manifest, result, analysis = run_positive_control_fixture(seed=302)
        bundle_path = save_experiment_bundle(self.temp_dir, manifest, result, analysis)

        # Tamper with result.json
        result_file = bundle_path / "result.json"
        result_file.write_text(result_file.read_text(encoding="utf-8") + " ", encoding="utf-8")

        res = verify_bundle_integrity(bundle_path)
        self.assertFalse(res["valid"])
        self.assertTrue(any("result.json" in m for m in res["mismatches"]))


class TestEndToEndWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rain_e2e_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_workflow_execution(self):
        manifest, result, analysis, bundle_path = run_experiment_workflow(
            question="Does 40Hz acoustic resonance alter phantom impedance?",
            hypothesis="40Hz stimulation induces impedance drop > 15%",
            frequency_hz=40.0,
            sample_count=30,
            seed=42,
            executor_name="simulated",
            base_dir=self.temp_dir,
            save_bundle=True,
        )

        self.assertEqual(manifest["protocol_version"], "1.0.0")
        self.assertEqual(result["executor_type"], "SIMULATED")
        self.assertEqual(result["provenance"], "SIMULATED")
        self.assertIn(analysis["conclusion"], ["SUPPORTS", "REFUTES", "INCONCLUSIVE"])
        self.assertTrue(bundle_path.exists())

        ver = verify_bundle_integrity(bundle_path)
        self.assertTrue(ver["valid"])


if __name__ == "__main__":
    unittest.main()
