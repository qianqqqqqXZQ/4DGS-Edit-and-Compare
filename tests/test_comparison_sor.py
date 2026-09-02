import io
import struct
import unittest

import numpy as np

import app as module


def _npy_bytes(array):
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=False)
    return stream.getvalue()


class ComparisonSorTests(unittest.TestCase):
    def setUp(self):
        self.previous_clouds = module.COMPARISON_STATE["clouds"]
        module.COMPARISON_STATE["clouds"] = {"a": None, "b": None}
        self.client = module.app.test_client()

    def tearDown(self):
        module.COMPARISON_STATE["clouds"] = self.previous_clouds

    @staticmethod
    def _fixture_points():
        cluster = np.array([[x, y, 0.0] for x in range(3) for y in range(3)], dtype=np.float32)
        return np.vstack([cluster, [[100.0, 100.0, 100.0]]]).astype(np.float32)

    def _load_fixture_comparison(self):
        points = self._fixture_points()
        response = self.client.post(
            "/api/comparison",
            data={
                "files": [
                    (io.BytesIO(_npy_bytes(points)), "a.npy"),
                    (io.BytesIO(_npy_bytes(points)), "b.npy"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return points

    def test_sor_filters_outlier_and_clamps_neighbors(self):
        points = self._fixture_points().astype(np.float64)
        mask, details = module._comparison_sor_filter(points, neighbors=999, stddev_multiplier=1.0)
        self.assertEqual(details["effective_neighbors"], len(points) - 1)
        self.assertFalse(mask[-1])
        self.assertTrue(mask[:-1].all())

    def test_sor_handles_small_cloud_without_mutating_input(self):
        points = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)
        original = points.copy()
        mask, details = module._comparison_sor_filter(points, neighbors=50, stddev_multiplier=1.0)
        np.testing.assert_array_equal(points, original)
        self.assertEqual(mask.tolist(), [True])
        self.assertEqual(details["effective_neighbors"], 0)

    def test_invalid_sor_parameters_are_rejected(self):
        self._load_fixture_comparison()
        for payload in (
            {"clouds": {"a": {"neighbors": 0}, "b": {"neighbors": 3}}},
            {"clouds": {"a": {"neighbors": 1.5}, "b": {"neighbors": 3}}},
            {"clouds": {"a": {"neighbors": 3, "stddev_multiplier": -1}, "b": {"neighbors": 3}}},
            {"clouds": {"a": {"neighbors": float("nan")}, "b": {"neighbors": 3}}},
        ):
            response = self.client.post("/api/comparison/sor", json=payload)
            self.assertEqual(response.status_code, 400, response.get_json())

    def test_sor_active_evaluation_reset_and_full_export(self):
        points = self._load_fixture_comparison()
        response = self.client.post(
            "/api/comparison/sor",
            json={
                "clouds": {
                    "a": {"neighbors": 3, "stddev_multiplier": 1.0},
                    "b": {"neighbors": 8, "stddev_multiplier": 0.0},
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.assertEqual(result["clouds"]["a"]["n_vertices"], 9)
        self.assertEqual(result["clouds"]["b"]["sor"]["neighbors"], 8)

        active_payload = self.client.get("/api/comparison/a").data
        self.assertEqual(struct.unpack("<I", active_payload[:4])[0], 9)

        evaluation = self.client.post(
            "/api/comparison/evaluate",
            json={
                "metrics": ["accuracy"],
                "tau": 0.05,
                "tau_max": 0.10,
                "transforms": {"a": {}, "b": {}},
            },
        )
        self.assertEqual(evaluation.status_code, 200, evaluation.get_json())
        report = evaluation.get_json()["markdown"]
        self.assertIn("Statistical Outlier Removal (SOR)", report)
        self.assertIn("Retained points", report)

        export = self.client.post(
            "/api/comparison/export",
            json={"cloud_id": "a", "format": "ply", "transform": {}},
        )
        self.assertEqual(export.status_code, 200)
        header = export.data.split(b"end_header\n", 1)[0].decode("ascii")
        self.assertIn(f"element vertex {len(points)}", header)

        reset = self.client.delete("/api/comparison/sor")
        self.assertEqual(reset.status_code, 200, reset.get_json())
        self.assertEqual(reset.get_json()["clouds"]["a"]["n_vertices"], len(points))
        reset_payload = self.client.get("/api/comparison/a").data
        self.assertEqual(struct.unpack("<I", reset_payload[:4])[0], len(points))

    def test_sor_requires_loaded_pair(self):
        response = self.client.post(
            "/api/comparison/sor",
            json={"clouds": {"a": {"neighbors": 3}, "b": {"neighbors": 3}}},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
