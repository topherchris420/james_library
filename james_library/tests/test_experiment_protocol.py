"""Comprehensive test suite for RAIN <-> CIRCLE Experiment Protocol."""

import shutil
import tempfile
import unittest
from copy import deepcopy
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

    def test_invalid_numeric_preregistration_is_rejected(self):
        manifest = design_experiment("Q", "H")
        pa = manifest["preregistered_analysis"]
        pa["alpha_threshold"] = float("nan")
        pa["minimum_effect_percent"] = -1
        pa["equivalence_margin_ohms"] = 0
        errors = validate_manifest(manifest)
        self.assertTrue(any("alpha_threshold" in error for error in errors))
        self.assertTrue(any("minimum_effect_percent" in error for error in errors))
        self.assertTrue(any("equivalence_margin_ohms" in error for error in errors))

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

    def test_welch_small_unequal_samples_match_reference_distribution(self):
        # Independently calculated with scipy.stats.ttest_ind(b, a, equal_var=False).
        a, b = [1.0, 2.0, 4.0], [0.0, 3.0, 10.0]
        t_stat, p_val, df = compute_p_value_two_sample(a, b)
        self.assertAlmostEqual(t_stat, 0.6469966392206302, places=12)
        self.assertAlmostEqual(df, 2.351669316375199, places=12)
        self.assertAlmostEqual(p_val, 0.5751237799117214, places=12)
        from math import sqrt
        se = sqrt(compute_variance(a) / len(a) + compute_variance(b) / len(b))
        ci = compute_confidence_interval(2.0, se, 0.95, df)
        self.assertAlmostEqual(ci[0], -9.564966757778379, places=9)
        self.assertAlmostEqual(ci[1], 13.564966757778379, places=9)

    def test_zero_variance_has_no_inferential_degrees_of_freedom(self):
        self.assertEqual(compute_p_value_two_sample([1.0, 1.0], [3.0, 3.0]), (0.0, 1.0, 0.0))

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
        self.assertEqual(analysis["conclusion"], "REFUTES")
        self.assertTrue(analysis["falsification_criteria_met"])
        self.assertTrue(analysis["statistical_results"]["equivalence_test"]["established"])
        self.assertFalse(analysis["artifact_analysis"]["phantom_signal_detected"])

    def test_high_p_value_without_equivalence_is_inconclusive(self):
        manifest, result, _ = run_negative_control_fixture(seed=202)
        noisy = deepcopy(result)
        noisy["_embedded_data"]["measurements"].update({
            "control": [80.0, 120.0] * 25,
            "active": [80.1, 119.9] * 25,
            "phantom": [80.0, 120.0] * 25,
        })
        analysis = run_deterministic_analysis(manifest, noisy, calculate_sha256(manifest))
        self.assertGreater(analysis["statistical_results"]["p_value"], 0.5)
        self.assertFalse(analysis["statistical_results"]["equivalence_test"]["established"])
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")

    def test_legacy_manifest_without_numeric_margin_cannot_refute(self):
        manifest, result, _ = run_negative_control_fixture(seed=202)
        legacy = deepcopy(manifest)
        del legacy["preregistered_analysis"]["equivalence_margin_ohms"]
        legacy_result = dict(result, manifest_sha256=calculate_sha256(legacy))
        analysis = run_deterministic_analysis(legacy, legacy_result, calculate_sha256(legacy))
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertFalse(analysis["falsification_criteria_met"])

    def test_wrong_direction_does_not_support_directional_claim(self):
        manifest, result, _ = run_positive_control_fixture(seed=201)
        reversed_result = deepcopy(result)
        values = reversed_result["_embedded_data"]["measurements"]["active"]
        reversed_result["_embedded_data"]["measurements"]["active"] = [v + 17.0 for v in values]
        analysis = run_deterministic_analysis(manifest, reversed_result, calculate_sha256(manifest))
        self.assertLess(analysis["statistical_results"]["p_value"], 0.05)
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")

    def test_small_precise_effect_cannot_support_registered_five_percent_claim(self):
        manifest, result, _ = run_positive_control_fixture(seed=201)
        small = deepcopy(result)
        small["_embedded_data"]["measurements"].update({
            "control": [100.0 + (i % 2) * 0.02 for i in range(50)],
            "active": [99.5 + (i % 2) * 0.02 for i in range(50)],
            "phantom": [100.0 + (i % 2) * 0.02 for i in range(50)],
        })
        analysis = run_deterministic_analysis(manifest, small, calculate_sha256(manifest))
        self.assertLess(analysis["statistical_results"]["p_value"], 0.05)
        self.assertEqual(analysis["conclusion"], "REFUTES")

    def test_overlapping_support_and_equivalence_remains_inconclusive(self):
        manifest, result, _ = run_positive_control_fixture(seed=201)
        overlapping = deepcopy(manifest)
        overlapping["preregistered_analysis"]["minimum_effect_percent"] = 0.0
        overlap_result = deepcopy(result)
        overlap_result["manifest_sha256"] = calculate_sha256(overlapping)
        overlap_result["_embedded_data"]["measurements"].update({
            "control": [100.0 + (i % 2) * 0.02 for i in range(50)],
            "active": [99.5 + (i % 2) * 0.02 for i in range(50)],
            "phantom": [100.0 + (i % 2) * 0.02 for i in range(50)],
        })
        analysis = run_deterministic_analysis(overlapping, overlap_result, calculate_sha256(overlapping))
        self.assertTrue(analysis["statistical_results"]["equivalence_test"]["established"])
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertIn("Both significance and equivalence", analysis["evidence_summary"])

    def test_zero_variance_analysis_is_inconclusive_without_interval(self):
        manifest, result, _ = run_positive_control_fixture(seed=201)
        flat = deepcopy(result)
        flat["_embedded_data"]["measurements"].update({
            "control": [100.0] * 30, "active": [90.0] * 30, "phantom": [100.0] * 30,
        })
        analysis = run_deterministic_analysis(manifest, flat, calculate_sha256(manifest))
        self.assertEqual(analysis["conclusion"], "INCONCLUSIVE")
        self.assertIsNone(analysis["confidence_intervals"]["lower_bound"])

    def test_nonfinite_measurement_is_rejected_before_conclusion(self):
        manifest, result, _ = run_negative_control_fixture(seed=202)
        invalid = deepcopy(result)
        invalid["_embedded_data"]["measurements"]["active"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            run_deterministic_analysis(manifest, invalid, calculate_sha256(manifest))

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
