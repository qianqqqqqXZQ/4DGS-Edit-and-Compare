import io
import os
import tempfile
import unittest

import numpy as np

import app as editor_app


class UsabilityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.client = editor_app.app.test_client()
        self.original_state = dict(editor_app.STATE)
        self.original_clouds = editor_app.COMPARISON_STATE["clouds"]
        editor_app._reset_workspace()
        editor_app.STATE.update({
            "loaded": True,
            "filename": "fixture.npy",
            "n_vertices": 2,
            "xyz": np.asarray([[0, 0, 0], [1, 0, 0]], dtype=np.float64),
            "quats": np.asarray([[1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.float64),
            "scales": np.ones((2, 3), dtype=np.float64),
            "opacities": np.ones(2, dtype=np.float64),
            "sh0": np.zeros((2, 3), dtype=np.float64),
            "sh_rest": np.zeros((2, 0, 3), dtype=np.float64),
            "colors": np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float64),
            "color_valid": np.asarray([True, True]),
            "part_id_array": np.asarray([0, 0], dtype=np.int32),
            "sh_degree": 0,
            "parts": {0: {"name": "Part 0", "color": [0, 0, 1], "pivot": [0, 0, 0], "vertex_indices": {0, 1}}},
            "tracks": {0: []},
            "4dgs_parts": {},
            "num_frames": 1,
        })

    def tearDown(self):
        editor_app.STATE.clear()
        editor_app.STATE.update(self.original_state)
        editor_app.COMPARISON_STATE["clouds"] = self.original_clouds

    def test_rgb_only_npy_keeps_sh_dc_zero(self):
        payload = io.BytesIO()
        np.save(payload, np.asarray([[0, 0, 0, 255, 0, 0]], dtype=np.float32))
        frame = editor_app.load_npy_bytes(payload.getvalue())
        np.testing.assert_allclose(frame["colors"], [[1, 0, 0]])
        np.testing.assert_allclose(frame["sh0"], [[0, 0, 0]])

    def test_pointcloud_color_modes_keep_original_and_part_color_distinct(self):
        original = self.client.get("/api/pointcloud?color_mode=original")
        part = self.client.get("/api/pointcloud?color_mode=part")
        self.assertEqual(original.status_code, 200)
        self.assertEqual(part.status_code, 200)
        original_colors = np.frombuffer(original.data, dtype="<f4", offset=4 + 2 * 3 * 4, count=6).reshape(2, 3)
        part_colors = np.frombuffer(part.data, dtype="<f4", offset=4 + 2 * 3 * 4, count=6).reshape(2, 3)
        np.testing.assert_allclose(original_colors, [[1, 0, 0], [0, 1, 0]])
        np.testing.assert_allclose(part_colors, [[0, 0, 1], [0, 0, 1]])

    def test_4dgs_directory_uses_natural_numeric_order(self):
        with tempfile.TemporaryDirectory(dir=editor_app.BASE_DIR) as directory:
            for name, value in (("frame_1.npy", 1), ("frame_10.npy", 10), ("frame_2.npy", 2)):
                np.save(os.path.join(directory, name), np.asarray([[value, 0, 0]], dtype=np.float32))
            loaded = editor_app.load_4dgs_dir(directory)
        self.assertEqual(loaded["filenames"], ["frame_1.npy", "frame_2.npy", "frame_10.npy"])
        self.assertEqual([frame["xyz"][0, 0] for frame in loaded["frames"]], [1, 2, 10])

    def test_part_name_rejects_control_characters_and_escapes_are_not_needed_in_api(self):
        rejected = self.client.put("/api/parts/0", json={"name": "bad\nname"})
        self.assertEqual(rejected.status_code, 400)
        accepted = self.client.put("/api/parts/0", json={"name": "<scene & part>"})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["part"]["name"], "<scene & part>")

    def test_destructive_part_delete_can_be_undone_once(self):
        deleted = self.client.delete("/api/parts/0/vertices")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(editor_app.STATE["n_vertices"], 0)
        self.assertTrue(self.client.get("/api/state").get_json()["can_undo"])
        restored = self.client.post("/api/undo")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(editor_app.STATE["n_vertices"], 2)
        self.assertIn(0, editor_app.STATE["parts"])
        self.assertFalse(self.client.get("/api/state").get_json()["can_undo"])

    def test_comparison_swap_preserves_a_complete_two_cloud_session(self):
        editor_app.COMPARISON_STATE["clouds"] = {
            "a": {"filename": "prediction.npy", "n_vertices": 1, "has_colors": False, "source": {"xyz": np.zeros((1, 3))}},
            "b": {"filename": "ground-truth.npy", "n_vertices": 1, "has_colors": False, "source": {"xyz": np.ones((1, 3))}},
        }
        response = self.client.post("/api/comparison/swap")
        self.assertEqual(response.status_code, 200)
        clouds = response.get_json()["clouds"]
        self.assertEqual([cloud["filename"] for cloud in clouds], ["ground-truth.npy", "prediction.npy"])
        metadata = self.client.get("/api/comparison")
        self.assertTrue(metadata.get_json()["loaded"])

    def test_mutating_json_routes_reject_non_object_bodies(self):
        for method, path in (
            ("post", "/api/parts"),
            ("put", "/api/parts/0"),
            ("post", "/api/parts/0/assign"),
            ("post", "/api/keyframes/0"),
            ("put", "/api/settings"),
            ("post", "/api/comparison/evaluate"),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, json=["not-an-object"])
                self.assertEqual(response.status_code, 400)
                self.assertIn("JSON object", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
