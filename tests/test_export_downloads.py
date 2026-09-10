import io
import unittest
import zipfile

import numpy as np

import app as editor_app


class ExportDownloadTests(unittest.TestCase):
    def setUp(self):
        self.client = editor_app.app.test_client()
        self.original_state = dict(editor_app.STATE)
        self.original_clouds = editor_app.COMPARISON_STATE["clouds"]
        editor_app._reset_workspace()
        editor_app.STATE.update({
            "loaded": True,
            "filename": "scene.ply",
            "n_vertices": 2,
            "xyz": np.asarray([[0, 0, 0], [1, 0, 0]], dtype=np.float64),
            "quats": np.asarray([[1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.float64),
            "scales": np.ones((2, 3), dtype=np.float64),
            "opacities": np.ones(2, dtype=np.float64),
            "sh0": np.zeros((2, 3), dtype=np.float64),
            "sh_rest": np.zeros((2, 0, 3), dtype=np.float64),
            "colors": np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float64),
            "color_valid": np.asarray([True, True]),
            "part_id_array": np.asarray([-1, -1], dtype=np.int32),
            "sh_degree": 0,
            "parts": {},
            "tracks": {},
            "4dgs_parts": {},
            "num_frames": 1,
        })

    def tearDown(self):
        editor_app.STATE.clear()
        editor_app.STATE.update(self.original_state)
        editor_app.COMPARISON_STATE["clouds"] = self.original_clouds

    def test_current_frame_download_returns_pt_without_server_path(self):
        response = self.client.post(
            "/api/export_current/download",
            json={"color_mode": "original"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("scene.frame_0000.pt", response.headers["Content-Disposition"])
        self.assertGreater(len(response.data), 32)

    def test_current_frame_download_uses_custom_name_and_normalizes_extension(self):
        response = self.client.post(
            "/api/export_current/download",
            json={"filename": "animated_scene.zip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("animated_scene.pt", response.headers["Content-Disposition"])

    def test_blank_editor_download_names_use_source_defaults(self):
        current = self.client.post("/api/export_current/download", json={"filename": "   "})
        self.assertEqual(current.status_code, 200)
        self.assertIn("scene.frame_0000.pt", current.headers["Content-Disposition"])

        archive = self.client.post("/api/export/download", json={"filename": ""})
        self.assertEqual(archive.status_code, 200)
        self.assertIn("scene.frames.zip", archive.headers["Content-Disposition"])

    def test_all_frames_download_returns_zip_without_server_path(self):
        response = self.client.post(
            "/api/export/download",
            json={"filename": "scene_bundle.pt", "color_mode": "edited"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("scene_bundle.zip", response.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["frame_0000.pt"])

    def test_frame_named_source_does_not_duplicate_frame_suffix(self):
        editor_app.STATE["filename"] = "frame_0000.pt"
        response = self.client.post("/api/export_current/download", json={})
        self.assertEqual(response.status_code, 200)
        self.assertIn("frame_0000.pt", response.headers["Content-Disposition"])

    def test_editor_download_rejects_filename_paths(self):
        for endpoint in ("/api/export_current/download", "/api/export/download"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, json={"filename": "../escape.pt"})
                self.assertEqual(response.status_code, 400)

    def test_comparison_export_accepts_custom_name_and_rejects_paths(self):
        editor_app.COMPARISON_STATE["clouds"] = {
            "a": {"filename": "source.ply", "source": {"xyz": np.zeros((1, 3))}},
            "b": {"filename": "target.ply", "source": {"xyz": np.ones((1, 3))}},
        }
        named = self.client.post(
            "/api/comparison/export",
            json={"cloud_id": "a", "format": "ply", "filename": "aligned_result.ply", "transform": {}},
        )
        self.assertEqual(named.status_code, 200)
        self.assertIn("aligned_result.ply", named.headers["Content-Disposition"])

        default_name = self.client.post(
            "/api/comparison/export",
            json={"cloud_id": "a", "format": "npy", "filename": "", "transform": {}},
        )
        self.assertEqual(default_name.status_code, 200)
        self.assertIn("source.transformed.npy", default_name.headers["Content-Disposition"])

        unsafe = self.client.post(
            "/api/comparison/export",
            json={"cloud_id": "a", "format": "ply", "filename": "../escape.ply", "transform": {}},
        )
        self.assertEqual(unsafe.status_code, 400)


if __name__ == "__main__":
    unittest.main()
