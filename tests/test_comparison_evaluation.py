import os
import unittest
from unittest import mock

import numpy as np

import app as editor_app


class ComparisonEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.client = editor_app.app.test_client()
        self.original_clouds = editor_app.COMPARISON_STATE["clouds"].copy()
        self.generated_paths = []

    def tearDown(self):
        editor_app.COMPARISON_STATE["clouds"] = self.original_clouds
        for path in self.generated_paths:
            if os.path.exists(path):
                os.remove(path)

    def load_comparison(self, points_a, points_b, filename_a="prediction.ply", filename_b="ground_truth.ply"):
        editor_app.COMPARISON_STATE["clouds"] = {
            "a": {"filename": filename_a, "source": {"xyz": np.asarray(points_a, dtype=np.float64)}},
            "b": {"filename": filename_b, "source": {"xyz": np.asarray(points_b, dtype=np.float64)}},
        }

    def evaluate(self, metrics, **extra):
        body = {"metrics": metrics, "tau": 0.05, "tau_max": 0.10}
        body.update(extra)
        response = self.client.post("/api/comparison/evaluate", json=body)
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.generated_paths.append(os.path.join(editor_app.EVALUATION_ROOT, result["filename"]))
        return result

    def test_kdtree_nearest_matches_bruteforce_reference(self):
        source = np.asarray([[0.1, 0.2, 0.3], [1.1, -0.2, 2.3], [2.2, 1.4, -0.4]])
        target = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 2.0], [2.0, 1.0, 0.0], [8.0, 8.0, 8.0]])

        distances, indices = editor_app._comparison_nearest(source, target, return_indices=True)
        squared = np.sum((source[:, None, :] - target[None, :, :]) ** 2, axis=2)
        expected_indices = np.argmin(squared, axis=1)
        expected_distances = np.sqrt(squared[np.arange(len(source)), expected_indices])

        np.testing.assert_allclose(distances, expected_distances, rtol=0, atol=1e-12)
        np.testing.assert_array_equal(indices, expected_indices)

    def test_accuracy_only_uses_one_directional_query(self):
        points_a = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        points_b = np.asarray([[0.1, 0.0, 0.0], [1.1, 0.0, 0.0]])
        self.load_comparison(points_a, points_b)
        original = editor_app._comparison_nearest
        calls = []

        def record(source, target, **kwargs):
            calls.append((len(source), len(target), kwargs.get("return_indices")))
            return original(source, target, **kwargs)

        with mock.patch.object(editor_app, "_comparison_nearest", side_effect=record):
            result = self.evaluate(["accuracy"])

        self.assertEqual(calls, [(2, 2, False)])
        self.assertEqual(result["selected_metrics"], ["accuracy"])
        self.assertEqual(set(result["values"]), {"accuracy"})
        self.assertEqual(result["query_engine"], "SciPy cKDTree (exact Euclidean)")
        self.assertGreaterEqual(result["runtime_seconds"], 0.0)

    def test_completeness_only_uses_ground_truth_to_prediction_query(self):
        points_a = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        points_b = np.asarray([[0.1, 0.0, 0.0], [1.1, 0.0, 0.0]])
        self.load_comparison(points_a, points_b)
        original = editor_app._comparison_nearest
        calls = []

        def record(source, target, **kwargs):
            calls.append((len(source), len(target), kwargs.get("return_indices")))
            return original(source, target, **kwargs)

        with mock.patch.object(editor_app, "_comparison_nearest", side_effect=record):
            result = self.evaluate(["completeness"])

        self.assertEqual(calls, [(2, 2, None)])
        self.assertEqual(set(result["values"]), {"completeness"})
        self.assertAlmostEqual(result["values"]["completeness"], 0.1)

    def test_all_metrics_emit_compact_metrics_first_report_and_download(self):
        points = np.asarray([[x, y, 0.0] for x in range(5) for y in range(5)], dtype=np.float64)
        self.load_comparison(points, points, "prediction|v1\nfinal.ply", "ground_truth.ply")
        result = self.evaluate([
            "accuracy", "completeness", "chamfer", "fscore", "auc", "normal_consistency",
        ], transforms={"a": {"tx": 0, "scale": 1}, "b": {"rz": 0, "scale": 1}})

        self.assertAlmostEqual(result["values"]["accuracy"], 0.0)
        self.assertAlmostEqual(result["values"]["completeness"], 0.0)
        self.assertAlmostEqual(result["values"]["chamfer"], 0.0)
        self.assertAlmostEqual(result["values"]["fscore"], 1.0)
        self.assertAlmostEqual(result["values"]["normal_consistency"], 1.0)
        markdown = result["markdown"]
        self.assertIn("# Comparison Metrics / ", markdown)
        self.assertIn("| Metric / ", markdown)
        self.assertIn("Accuracy (Acc.)", markdown)
        self.assertIn("F-Score (F1)", markdown)
        self.assertIn("P=1.00000000, R=1.00000000", markdown)
        self.assertIn("prediction\\|v1 final.ply", markdown)
        self.assertIn("\u5bf9\u6bd4\u6307\u6807", markdown)
        self.assertNotIn("Evaluation Configuration", markdown)
        self.assertNotIn("Applied Transforms", markdown)
        self.assertNotIn("Method Notes", markdown)

        download = self.client.get(result["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "text/markdown")
        self.assertEqual(download.get_data(as_text=True), markdown)
        download.close()

    def test_threshold_boundary_and_degenerate_normal_consistency(self):
        points_a = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        points_b = np.asarray([[0.05, 0.0, 0.0], [1.05, 0.0, 0.0]])
        self.load_comparison(points_a, points_b)
        result = self.evaluate(["fscore", "normal_consistency"])

        self.assertEqual(result["values"]["fscore"], 0.0)
        self.assertIsNone(result["values"]["normal_consistency"])
        self.assertIn("NC requires non-degenerate local PCA neighbourhoods", result["markdown"])
        self.assertIsNone(editor_app._comparison_normals(np.zeros((3, 3), dtype=np.float64)))

    def test_transforms_apply_before_metric_calculation(self):
        points_a = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        points_b = points_a + np.asarray([2.0, -3.0, 4.0])
        self.load_comparison(points_a, points_b)
        result = self.evaluate(
            ["accuracy", "completeness", "chamfer"],
            transforms={"a": {"tx": 2.0, "ty": -3.0, "tz": 4.0}, "b": {}},
        )

        self.assertAlmostEqual(result["values"]["accuracy"], 0.0)
        self.assertAlmostEqual(result["values"]["completeness"], 0.0)
        self.assertAlmostEqual(result["values"]["chamfer"], 0.0)


if __name__ == "__main__":
    unittest.main()
