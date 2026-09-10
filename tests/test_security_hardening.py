import io
import os
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

import app as editor_app


def _unsafe_write(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("unsafe pickle executed")
    return {"xyz": [[0.0, 0.0, 0.0]]}


class UnsafePayload:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return _unsafe_write, (self.path,)


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        if editor_app.torch is None:
            self.skipTest("PyTorch is required for checkpoint security tests")
        self.client = editor_app.app.test_client()
        self.temp_root = tempfile.mkdtemp(prefix="security_hardening_", dir=editor_app.BASE_DIR)
        self.external_root = tempfile.mkdtemp(prefix="security_hardening_external_")
        self.original_allowed_paths = os.environ.get("EDITOR_ALLOWED_PATHS")
        self.original_upload_root = editor_app.UPLOAD_ROOT
        self.original_state = dict(editor_app.STATE)
        self.original_clouds = editor_app.COMPARISON_STATE["clouds"]
        self.upload_root = os.path.join(self.temp_root, "uploads")
        os.makedirs(self.upload_root)
        editor_app.UPLOAD_ROOT = self.upload_root
        os.environ.pop("EDITOR_ALLOWED_PATHS", None)
        editor_app._reset_workspace()
        editor_app.STATE.update({
            "loaded": True,
            "filename": "secure_fixture.pt",
            "n_vertices": 1,
            "xyz": np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64),
            "quats": np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
            "scales": np.ones((1, 3), dtype=np.float64),
            "opacities": np.ones(1, dtype=np.float64),
            "sh0": np.zeros((1, 3), dtype=np.float64),
            "sh_rest": np.zeros((1, 0, 3), dtype=np.float64),
            "colors": np.ones((1, 3), dtype=np.float64),
            "color_valid": np.asarray([True]),
            "part_id_array": np.asarray([-1], dtype=np.int32),
            "sh_degree": 0,
            "parts": {},
            "tracks": {},
            "4dgs_parts": {},
            "num_frames": 1,
        })

    def tearDown(self):
        editor_app.UPLOAD_ROOT = self.original_upload_root
        editor_app.STATE.clear()
        editor_app.STATE.update(self.original_state)
        editor_app.COMPARISON_STATE["clouds"] = self.original_clouds
        if self.original_allowed_paths is None:
            os.environ.pop("EDITOR_ALLOWED_PATHS", None)
        else:
            os.environ["EDITOR_ALLOWED_PATHS"] = self.original_allowed_paths
        shutil.rmtree(self.temp_root, ignore_errors=True)
        shutil.rmtree(self.external_root, ignore_errors=True)

    def checkpoint_bytes(self, payload):
        buffer = io.BytesIO()
        editor_app.torch.save(payload, buffer)
        return buffer.getvalue()

    def assert_load_rejected(self, payload, message):
        with self.assertRaisesRegex(ValueError, message):
            editor_app.load_pt_bytes(self.checkpoint_bytes(payload))

    def test_safe_raw_flat_nested_and_frames_checkpoints_load(self):
        torch = editor_app.torch
        raw = torch.tensor([[0.0, 1.0, 2.0, 1.0, 0.0, 0.0]], dtype=torch.float32)
        flat = {
            "means": torch.tensor([[0.0, 0.0, 0.0]], dtype=torch.float32),
            "quats": torch.tensor([[1.0, 0.0, 0.0, 0.0]], dtype=torch.float32),
            "scales": torch.ones((1, 3)),
            "opacities": torch.ones(1),
            "sh0": torch.zeros((1, 1, 3)),
            "shN": torch.zeros((1, 0, 3)),
        }
        nested = {"splats": flat, "sh_degree": 0}
        framed = {"frames": [nested]}
        for payload in (raw, flat, nested, framed):
            frame = editor_app.load_pt_bytes(self.checkpoint_bytes(payload))
            self.assertEqual(frame["xyz"].shape, (1, 3))
            self.assertEqual(frame["n_vertices"], 1)

    def test_invalid_xyz_and_attribute_layouts_are_rejected(self):
        torch = editor_app.torch
        self.assert_load_rejected({"xyz": torch.zeros((1, 2))}, "shape")
        self.assert_load_rejected({"xyz": torch.zeros((0, 3))}, "at least one")
        self.assert_load_rejected({"xyz": torch.tensor([[float("nan"), 0, 0]])}, "finite")
        self.assert_load_rejected({"xyz": torch.zeros((2, 3)), "quats": torch.zeros((1, 4))}, "quaternions")
        self.assert_load_rejected({"xyz": torch.zeros((2, 3)), "colors": torch.zeros((1, 3))}, "RGB")
        self.assert_load_rejected({"xyz": torch.zeros((2, 3)), "sh0": torch.zeros((2, 2))}, "SH DC")
        self.assert_load_rejected({"xyz": torch.zeros((2, 3)), "shN": torch.zeros((1, 3, 3))}, "SH rest")
        self.assert_load_rejected({"xyz": torch.zeros((1, 3)), "shN": torch.zeros((1, 1, 3)), "sh_degree": 0}, "SH rest coefficient")
        self.assert_load_rejected({"unknown": torch.zeros((1, 3))}, "XYZ")

    def test_weights_only_rejects_pickle_without_executing_it(self):
        marker = os.path.join(self.temp_root, "pickle-executed.txt")
        with self.assertRaisesRegex(ValueError, "Unsafe or unreadable"):
            editor_app.load_pt_bytes(self.checkpoint_bytes(UnsafePayload(marker)))
        self.assertFalse(os.path.exists(marker))

    def test_npy_and_ply_reject_empty_or_nonfinite_xyz(self):
        empty = io.BytesIO()
        np.save(empty, np.empty((0, 3), dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "at least one"):
            editor_app.load_npy_bytes(empty.getvalue())
        invalid = io.BytesIO()
        np.save(invalid, np.asarray([[np.inf, 0.0, 0.0]], dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "finite"):
            editor_app.load_npy_bytes(invalid.getvalue())
        empty_ply = b"ply\nformat ascii 1.0\nelement vertex 0\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
        with self.assertRaisesRegex(ValueError, "at least one"):
            editor_app.load_ply_bytes(empty_ply)

    def test_server_paths_are_allowlisted_and_parent_traversal_is_rejected(self):
        allowed = os.path.join(editor_app.BASE_DIR, "generated", "security-tests")
        outside = os.path.join(self.external_root, "outside")
        os.makedirs(allowed, exist_ok=True)
        os.makedirs(outside, exist_ok=True)
        try:
            self.assertEqual(editor_app._resolve_user_path(allowed), os.path.realpath(allowed))
            with self.assertRaisesRegex(ValueError, "allowlist"):
                editor_app._resolve_user_path(outside)
            with self.assertRaisesRegex(ValueError, "traversal"):
                editor_app._resolve_user_path(os.path.join(editor_app.BASE_DIR, "generated", "..", "escape.pt"))
            for route, body in (
                ("/api/export", {"output_dir": outside}),
                ("/api/export_current", {"output_path": os.path.join(outside, "current.pt")}),
                ("/api/export/current", {"output_path": os.path.join(outside, "legacy.pt")}),
                ("/api/export/all", {"output_dir": outside}),
            ):
                response = self.client.post(route, json=body)
                self.assertEqual(response.status_code, 400, (route, response.get_json()))
            for route in ("/api/upload_4dgs", "/api/export", "/api/export_current", "/api/export/current", "/api/export/all"):
                response = self.client.post(route, json=[])
                self.assertEqual(response.status_code, 400, (route, response.get_json()))
        finally:
            shutil.rmtree(allowed, ignore_errors=True)

    def test_allowlist_supports_explicit_external_directory_and_blocks_symlink_escape(self):
        allowed = os.path.join(self.temp_root, "allowed")
        outside = os.path.join(self.external_root, "outside")
        os.makedirs(allowed)
        os.makedirs(outside)
        os.environ["EDITOR_ALLOWED_PATHS"] = allowed
        self.assertEqual(editor_app._resolve_user_path(os.path.join(allowed, "output.pt")), os.path.join(allowed, "output.pt"))
        with self.assertRaisesRegex(ValueError, "allowlist"):
            editor_app._resolve_user_path(os.path.join(outside, "output.pt"))
        link = os.path.join(allowed, "escape-link")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (NotImplementedError, OSError):
            # Windows commonly blocks symbolic links for non-elevated test
            # processes. A directory junction exercises the same realpath
            # escape condition without requiring the developer-mode privilege.
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", link, outside],
                check=False,
                capture_output=True,
                text=True,
            )
            if junction.returncode != 0:
                self.skipTest("symbolic links and directory junctions are unavailable for this Windows test process")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            editor_app._resolve_user_path(os.path.join(link, "output.pt"))

    def test_4dgs_directory_path_is_checked_before_loading(self):
        outside = os.path.join(self.external_root, "outside-frames")
        os.makedirs(outside)
        response = self.client.post("/api/upload_4dgs", json={"dir_path": outside})
        self.assertEqual(response.status_code, 400)
        self.assertIn("allowlist", response.get_json()["error"])
        allowed = os.path.join(self.temp_root, "allowed-frames")
        os.makedirs(allowed)
        editor_app.torch.save(editor_app.torch.zeros((1, 3)), os.path.join(allowed, "frame_0000.pt"))
        response = self.client.post("/api/upload_4dgs", json={"dir_path": allowed})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_upload_temp_directories_are_removed_after_success_and_failure(self):
        valid = self.checkpoint_bytes(editor_app.torch.zeros((1, 3)))
        response = self.client.post(
            "/api/upload",
            data={"files": (io.BytesIO(valid), "valid.pt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(os.listdir(self.upload_root), [])
        invalid = self.checkpoint_bytes(editor_app.torch.zeros((0, 3)))
        response = self.client.post(
            "/api/upload_append",
            data={"files": (io.BytesIO(invalid), "invalid.pt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(os.listdir(self.upload_root), [])


if __name__ == "__main__":
    unittest.main()
