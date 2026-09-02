import io
import json
import math
import os
import shutil
import struct
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from flask import Flask, Response, jsonify, request, send_file

try:
    import torch
except Exception:
    torch = None

try:
    from plyfile import PlyData
except Exception:
    PlyData = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.join(BASE_DIR, "generated")
os.makedirs(EXPORT_ROOT, exist_ok=True)
EVALUATION_ROOT = os.path.join(EXPORT_ROOT, "evaluations")
os.makedirs(EVALUATION_ROOT, exist_ok=True)
UPLOAD_ROOT = os.path.join(tempfile.gettempdir(), "part_level_4dgs_uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

PART_COLORS = [
    [0.9, 0.2, 0.2],
    [0.2, 0.7, 0.2],
    [0.2, 0.4, 0.9],
    [0.9, 0.7, 0.1],
    [0.7, 0.2, 0.8],
    [0.1, 0.8, 0.8],
    [0.9, 0.5, 0.2],
    [0.5, 0.9, 0.3],
    [0.3, 0.5, 0.9],
]
C0 = 0.28209479177387814
SUPPORTED_POINTCLOUD_EXTENSIONS = (".ply", ".pt", ".npy")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 400 * 1024 * 1024

STATE: Dict[str, Any] = {
    "loaded": False,
    "filename": "",
    "n_vertices": 0,
    "xyz": None,
    "quats": None,
    "scales": None,
    "opacities": None,
    "sh0": None,
    "sh_rest": None,
    "colors": None,
    "color_valid": None,
    "sh_degree": 0,
    "part_id_array": None,
    "parts": {},
    "next_part_id": 0,
    "tracks": {},
    "num_frames": 1,
    "interpolation_method": "linear",
    "export_progress": -1,
    "export_dir": None,
    "export_done": False,
    "export_active": False,
    "4dgs_parts": {},
}
STATE_LOCK = threading.RLock()

# Comparison data is deliberately kept outside the editor STATE so a comparison
# upload cannot change Parts, keyframes, exports, or the active workspace.
_COMPARISON_SOR_DEFAULTS = {"neighbors": 50, "stddev_multiplier": 1.0}
COMPARISON_STATE: Dict[str, Any] = {"clouds": {"a": None, "b": None}}


def _arr(value: Any, shape: Tuple[int, ...], default: float = 0.0) -> np.ndarray:
    if value is None:
        return np.full(shape, default, dtype=np.float64)
    a = np.asarray(value, dtype=np.float64)
    if a.size == int(np.prod(shape)):
        return a.reshape(shape)
    out = np.full(shape, default, dtype=np.float64)
    flat = a.reshape(-1)
    out.reshape(-1)[: min(flat.size, out.size)] = flat[: out.size]
    return out


def _field(obj: Any, names: List[str], default: Any = None) -> Any:
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _normalise_rgb(value: Any, n: int) -> Optional[np.ndarray]:
    """Normalise an explicit RGB field to an ``(n, 3)`` float array."""
    if value is None or n <= 0:
        return None
    try:
        array = value.detach().cpu().numpy() if hasattr(value, "detach") else np.asarray(value)
        array = np.asarray(array, dtype=np.float64)
        if array.size != n * 3:
            return None
        array = array.reshape((n, 3))
        if not np.isfinite(array).all():
            return None
        if np.max(np.abs(array)) > 1.0:
            array = array / 255.0
        return np.clip(array, 0.0, 1.0)
    except (TypeError, ValueError):
        return None


def _normalise_frame(obj: Any) -> Dict[str, Any]:
    xyz = _field(obj, ["xyz", "means3D", "means", "positions", "pos", "points"])
    if xyz is None and isinstance(obj, (list, tuple)) and len(obj) >= 1:
        xyz = obj[0]
    xyz = np.asarray(xyz if xyz is not None else np.zeros((0, 3)), dtype=np.float64)
    if xyz.ndim == 1:
        xyz = xyz.reshape((-1, 3))
    if xyz.shape[-1] > 3:
        xyz = xyz[:, :3]
    n = len(xyz)
    quats = _field(obj, ["quats", "rotation", "rotations", "rots"])
    quats = _arr(quats, (n, 4), 0.0)
    if quats.size and np.allclose(quats, 0):
        quats[:, 0] = 1.0
    scales = _field(obj, ["scales", "scale", "scaling"])
    scales = _arr(scales, (n, 3), 0.0)
    opacities = _field(obj, ["opacities", "opacity", "alpha"])
    opacities = _arr(opacities, (n,), 0.0)
    explicit_colors = _normalise_rgb(_field(obj, ["colors", "rgb", "color"]), n)
    sh0 = _field(obj, ["sh0", "features_dc", "colors", "rgb", "color"])
    sh0 = _arr(sh0, (n, 3), 0.0)
    sh_rest = _field(obj, ["sh_rest", "features_rest"])
    if sh_rest is not None:
        sr = np.asarray(sh_rest, dtype=np.float64)
        if sr.ndim == 2 and sr.shape[0] == n:
            sr = sr.reshape((n, -1, 3)) if sr.shape[1] % 3 == 0 else None
        elif sr.ndim == 3 and sr.shape[0] != n and sr.shape[1] == n:
            sr = np.transpose(sr, (1, 0, 2))
        sh_rest = sr
    degree = int(_field(obj, ["sh_degree", "degree"], 0) or 0)
    return {"xyz": xyz, "quats": quats, "scales": scales, "opacities": opacities,
            "sh0": sh0, "sh_rest": sh_rest, "sh_degree": degree, "n_vertices": n,
            "colors": explicit_colors, "has_colors": explicit_colors is not None}


def load_ply_bytes(data: bytes) -> Dict[str, Any]:
    if PlyData is None:
        raise RuntimeError("plyfile is required to read PLY files. Install with: pip install plyfile")
    ply = PlyData.read(io.BytesIO(data))
    vertex = ply["vertex"]
    names = set(vertex.data.dtype.names or [])
    xyz = np.stack([vertex[axis] for axis in ("x", "y", "z")], axis=1).astype(np.float64)
    n = len(xyz)
    has_colors = all(c in names for c in ("red", "green", "blue"))
    colors = np.zeros((n, 3), dtype=np.float64) if has_colors else None
    if has_colors:
        for i, c in enumerate(("red", "green", "blue")):
            channel = np.asarray(vertex[c], dtype=np.float64)
            colors[:, i] = channel / (255.0 if np.max(channel) > 1.0 else 1.0)
    quats = np.zeros((n, 4), dtype=np.float64); quats[:, 0] = 1.0
    qnames = [("rot_0", 0), ("rot_1", 1), ("rot_2", 2), ("rot_3", 3)]
    if all(k in names for k, _ in qnames):
        quats = np.stack([vertex[k] for k, _ in qnames], axis=1).astype(np.float64)
    scale_names = [("scale_0", "scale_x"), ("scale_1", "scale_y"), ("scale_2", "scale_z")]
    scales = np.stack([np.asarray(vertex[next(name for name in aliases if name in names)], dtype=np.float64) if any(name in names for name in aliases) else np.zeros(n) for aliases in scale_names], axis=1)
    opacities = np.asarray(vertex["opacity"], dtype=np.float64) if "opacity" in names else np.zeros(n)
    sh0 = np.zeros((n, 3), dtype=np.float64)
    for i, key in enumerate(("f_dc_0", "f_dc_1", "f_dc_2")):
        if key in names: sh0[:, i] = np.asarray(vertex[key], dtype=np.float64)
    rest_keys = sorted([k for k in names if k.startswith("f_rest_")], key=lambda x: int(x.split("_")[-1]))
    sh_rest = None
    if rest_keys and len(rest_keys) % 3 == 0:
        sh_rest = np.stack([vertex[k] for k in rest_keys], axis=1).reshape((n, -1, 3)).astype(np.float64)
    n_rest = int(sh_rest.shape[1] * 3) if sh_rest is not None else 0
    degree = int(math.sqrt(n_rest // 3 + 1)) - 1 if n_rest else 0
    return {"xyz": xyz, "quats": quats, "scales": scales, "opacities": opacities,
            "sh0": sh0, "sh_rest": sh_rest, "sh_degree": max(degree, 0), "n_vertices": n,
            "colors": colors, "has_colors": has_colors}


def load_pt_bytes(data: bytes) -> Dict[str, Any]:
    if torch is None:
        raise RuntimeError("PyTorch is required to read .pt files. Install torch first.")
    obj = torch.load(io.BytesIO(data), map_location="cpu", weights_only=False)
    if isinstance(obj, torch.Tensor):
        if obj.ndim != 2 or obj.shape[1] < 3:
            raise ValueError("Raw .pt tensors must have shape (N, >=3).")
        # Raw tensors are simple point rows: xyz, optional RGB, then ignored fields.
        raw = obj.detach().cpu().numpy()
        obj = {"xyz": raw[:, :3]}
        if raw.shape[1] >= 6:
            obj["colors"] = raw[:, 3:6]
    if isinstance(obj, dict) and "frames" in obj and isinstance(obj["frames"], (list, tuple)):
        obj = obj["frames"][0]
    if isinstance(obj, dict) and isinstance(obj.get("splats"), dict):
        splats = obj["splats"]
        obj = {**splats, "sh_degree": obj.get("sh_degree", 0)}
    if isinstance(obj, (list, tuple)) and obj and isinstance(obj[0], (dict, tuple, list)):
        obj = obj[0]
    def to_np(v):
        return v.detach().cpu().numpy() if hasattr(v, "detach") else v
    if isinstance(obj, dict):
        obj = {k: to_np(v) for k, v in obj.items()}
    frame = _normalise_frame(obj)
    if isinstance(obj, dict) and "sh0" in obj:
        frame["sh0"] = np.asarray(obj["sh0"], dtype=np.float64).reshape((frame["n_vertices"], -1, 3))[:, 0, :]
    if isinstance(obj, dict) and "shN" in obj:
        sr = np.asarray(obj["shN"], dtype=np.float64)
        if sr.size == 0:
            frame["sh_rest"] = None
        elif sr.ndim == 2:
            frame["sh_rest"] = sr.reshape((frame["n_vertices"], -1, 3))
        elif sr.ndim == 3 and sr.shape[0] == frame["n_vertices"]:
            frame["sh_rest"] = sr.reshape((frame["n_vertices"], -1, 3))
    # Re-check explicit RGB after flattening nested checkpoints and normalise
    # common 0..255 tensors without changing the SH values used for export.
    if isinstance(obj, dict):
        frame["colors"] = _normalise_rgb(_field(obj, ["colors", "rgb", "color"]), frame["n_vertices"])
        frame["has_colors"] = frame["colors"] is not None
    frame["sh_degree"] = int(obj.get("sh_degree", frame.get("sh_degree", 0))) if isinstance(obj, dict) else frame.get("sh_degree", 0)
    return frame


def load_npy_bytes(data: bytes) -> Dict[str, Any]:
    """Load an ``N x >=3`` NumPy array as a point cloud."""
    try:
        array = np.load(io.BytesIO(data), allow_pickle=False)
    except (OSError, ValueError, EOFError) as exc:
        raise ValueError(f"Invalid .npy file: {exc}") from exc
    if not isinstance(array, np.ndarray) or array.ndim != 2 or array.shape[1] < 3:
        raise ValueError("Raw .npy arrays must have shape (N, >=3).")
    try:
        raw = np.asarray(array, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("Raw .npy arrays must contain numeric values.") from exc
    if not np.isfinite(raw[:, :3]).all():
        raise ValueError("Raw .npy XYZ coordinates must be finite.")
    payload = {"xyz": raw[:, :3]}
    if raw.shape[1] >= 6:
        payload["colors"] = raw[:, 3:6]
    return _normalise_frame(payload)


def load_ply(filepath: str) -> Dict[str, Any]:
    """Load a PLY file into the editor's canonical NumPy representation."""
    with open(filepath, "rb") as handle:
        return load_ply_bytes(handle.read())


def load_pt(filepath: str) -> Dict[str, Any]:
    """Load a gsplat checkpoint (nested ``splats`` or flat) from disk."""
    with open(filepath, "rb") as handle:
        return load_pt_bytes(handle.read())


def load_npy(filepath: str) -> Dict[str, Any]:
    """Load an ``N x >=3`` NumPy point-cloud array from disk."""
    with open(filepath, "rb") as handle:
        return load_npy_bytes(handle.read())


def _load_pointcloud_path(filepath: str, extension: Optional[str] = None) -> Dict[str, Any]:
    ext = (extension or os.path.splitext(filepath)[1]).lower()
    if ext == ".ply":
        return load_ply(filepath)
    if ext == ".pt":
        return load_pt(filepath)
    if ext == ".npy":
        return load_npy(filepath)
    raise ValueError(f"Unsupported file type: {os.path.basename(filepath) or '<unnamed>'}")


def _load_pointcloud_bytes(data: bytes, extension: str) -> Dict[str, Any]:
    ext = extension.lower()
    if ext == ".ply":
        return load_ply_bytes(data)
    if ext == ".pt":
        return load_pt_bytes(data)
    if ext == ".npy":
        return load_npy_bytes(data)
    raise ValueError(f"Unsupported file type: {extension or '<unnamed>'}")


def save_frame_as_pt(xyz, quats, scales, opacities, sh0, sh_rest, sh_degree, filepath, colors=None):
    """Write one canonical frame using the gsplat checkpoint schema."""
    if torch is None:
        raise RuntimeError("PyTorch is required to save .pt files")
    xyz = np.asarray(xyz); n = len(xyz)
    splats = {
        "means": torch.from_numpy(xyz.astype(np.float32)),
        "quats": torch.from_numpy(np.asarray(quats).reshape(n, 4).astype(np.float32)),
        "scales": torch.from_numpy(np.asarray(scales).reshape(n, 3).astype(np.float32)),
        "opacities": torch.from_numpy(np.asarray(opacities).reshape(n).astype(np.float32)),
        "sh0": torch.from_numpy(np.asarray(sh0).reshape(n, 3).astype(np.float32)).reshape(n, 1, 3),
    }
    if colors is not None:
        splats["colors"] = torch.from_numpy(np.asarray(colors).reshape(n, 3).astype(np.float32))
    if sh_rest is None:
        splats["shN"] = torch.zeros((n, 0, 3), dtype=torch.float32)
    else:
        splats["shN"] = torch.from_numpy(np.asarray(sh_rest).reshape(n, -1, 3).astype(np.float32))
    # Keep the canonical nested gsplat payload and expose the same fields at
    # the top level so exported checkpoints are directly torch.load()-friendly.
    torch.save({**splats, "splats": splats, "sh_degree": int(sh_degree)}, filepath)


def _pad_sh_rest(rest, n, target_k):
    out = np.zeros((n, target_k, 3), dtype=np.float64)
    if n == 0:
        return out
    if rest is not None:
        a = np.asarray(rest, dtype=np.float64).reshape(n, -1, 3)
        out[:, :min(target_k, a.shape[1]), :] = a[:, :target_k, :]
    return out


def sh_to_rgb(sh0: Any) -> np.ndarray:
    """Convert the DC spherical-harmonic coefficients to clipped RGB."""
    return np.clip(np.asarray(sh0, dtype=np.float64) * C0 + 0.5, 0, 1)


def _original_colors(source: Dict[str, Any]) -> np.ndarray:
    """Return explicit source RGB, falling back to SH DC colors or neutral gray."""
    count = int(source.get("n_vertices", len(source.get("xyz", []))))
    fallback = sh_to_rgb(source.get("sh0", np.zeros((count, 3), dtype=np.float64)))
    if len(fallback) != count:
        fallback = np.full((count, 3), 0.5, dtype=np.float64)
    colors = _normalise_rgb(source.get("colors"), count)
    if colors is None:
        return fallback
    valid = source.get("color_valid")
    if valid is None:
        valid = np.full(count, bool(source.get("has_colors", False)), dtype=bool)
    valid = np.asarray(valid, dtype=bool).reshape(count)
    out = np.array(fallback, dtype=np.float64, copy=True)
    out[valid] = colors[valid]
    return out


def load_4dgs_dir(dir_path: str) -> Dict[str, Any]:
    """Load sorted ``.pt``/``.npy`` frames and pad all SH tensors to the maximum degree."""
    path = Path(dir_path)
    if not path.is_dir():
        raise FileNotFoundError(f"4DGS directory not found: {dir_path}")
    files = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() in (".pt", ".npy")), key=lambda p: p.name.lower())
    if not files:
        raise ValueError(f"No .pt or .npy frames found in {dir_path}")
    frames = [_load_pointcloud_path(str(p)) for p in files]
    max_degree = max(int(f.get("sh_degree", 0)) for f in frames)
    target_k = max(0, (max_degree + 1) ** 2 - 1)
    for frame in frames:
        frame["sh_rest"] = _pad_sh_rest(frame.get("sh_rest"), frame["n_vertices"], target_k)
        frame["sh_degree"] = max_degree
    return {"frames": frames, "n_frames_src": len(frames), "sh_degree": max_degree,
            "filenames": [p.name for p in files]}


def _get_4dgs_frame_idx(pid: int, frame: int) -> int:
    info = STATE["4dgs_parts"][pid]
    n_src = int(info["n_frames_src"])
    if n_src <= 0:
        return 0
    return frame % n_src if info.get("loop", False) else min(frame, n_src - 1)


def euler_to_rotation_matrix(rx_deg, ry_deg, rz_deg):
    rx, ry, rz = np.deg2rad([rx_deg, ry_deg, rz_deg])
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def rotation_matrix_to_quaternion(R):
    R = np.asarray(R, dtype=np.float64).reshape(3, 3); trace = np.trace(R)
    if trace > 0:
        s = 2 * np.sqrt(trace + 1); q = np.array([0.25*s, (R[2,1]-R[1,2])/s, (R[0,2]-R[2,0])/s, (R[1,0]-R[0,1])/s])
    else:
        i = int(np.argmax(np.diag(R)))
        if i == 0:
            s = 2*np.sqrt(max(1+R[0,0]-R[1,1]-R[2,2], 1e-15)); q = np.array([(R[2,1]-R[1,2])/s, .25*s, (R[0,1]+R[1,0])/s, (R[0,2]+R[2,0])/s])
        elif i == 1:
            s = 2*np.sqrt(max(1+R[1,1]-R[0,0]-R[2,2], 1e-15)); q = np.array([(R[0,2]-R[2,0])/s, (R[0,1]+R[1,0])/s, .25*s, (R[1,2]+R[2,1])/s])
        else:
            s = 2*np.sqrt(max(1+R[2,2]-R[0,0]-R[1,1], 1e-15)); q = np.array([(R[1,0]-R[0,1])/s, (R[0,2]+R[2,0])/s, (R[1,2]+R[2,1])/s, .25*s])
    return q / max(np.linalg.norm(q), 1e-15)


def quaternion_multiply(q1, q2):
    a, b = np.asarray(q1, dtype=np.float64), np.asarray(q2, dtype=np.float64)
    a, b = np.broadcast_arrays(a, b); w1,x1,y1,z1 = np.moveaxis(a, -1, 0); w2,x2,y2,z2 = np.moveaxis(b, -1, 0)
    return np.stack((w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2, w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2), axis=-1)


def lerp(a, b, t):
    return np.asarray(a) + t * (np.asarray(b) - np.asarray(a))


def interpolate_keyframes(keyframes: list, frame: int, method: str = "linear") -> dict:
    names = ("tx", "ty", "tz", "rx", "ry", "rz")
    if not keyframes:
        return {"frame": frame, **{k: 0.0 for k in names}}
    keys = sorted(keyframes, key=lambda x: x.get("frame", 0))
    if frame <= keys[0].get("frame", 0): return {"frame": frame, **{k: float(keys[0].get(k, 0)) for k in names}}
    if frame >= keys[-1].get("frame", 0): return {"frame": frame, **{k: float(keys[-1].get(k, 0)) for k in names}}
    hi = next(i for i, k in enumerate(keys) if k.get("frame", 0) >= frame); a, b = keys[hi-1], keys[hi]; t = (frame-a["frame"]) / max(1, b["frame"]-a["frame"])
    result = {"frame": frame}
    for k in names:
        if method in ("catmull_rom", "catmull-rom") and k in ("tx", "ty", "tz") and len(keys) >= 2:
            p0, p3 = keys[max(0, hi-2)], keys[min(len(keys)-1, hi+1)]; v0,v1,v2,v3 = [float(x.get(k,0)) for x in (p0,a,b,p3)]
            result[k] = .5*((2*v1)+(-v0+v2)*t+(2*v0-5*v1+4*v2-v3)*t*t+(-v0+3*v1-3*v2+v3)*t*t*t)
        else: result[k] = float(lerp(a.get(k,0), b.get(k,0), t))
    return result


def _apply_transform_to_data(xyz, quats, pivot, tf):
    xyz = np.asarray(xyz, dtype=np.float64); quats = np.asarray(quats, dtype=np.float64)
    # Keyframe tracks store radians; the public Euler helper accepts degrees.
    R = euler_to_rotation_matrix(*np.rad2deg([tf.get("rx", 0), tf.get("ry", 0), tf.get("rz", 0)])); p = np.asarray(pivot, dtype=np.float64)
    t = np.asarray([tf.get("tx", 0), tf.get("ty", 0), tf.get("tz", 0)], dtype=np.float64)
    if np.allclose(R, np.eye(3)) and np.allclose(t, 0): return xyz.copy(), quats.copy()
    rq = rotation_matrix_to_quaternion(R)
    return (xyz-p) @ R.T + p + t, quaternion_multiply(rq, quats)


def _serialize_part(pid: int, part: Dict[str, Any]) -> Dict[str, Any]:
    indices = sorted(int(index) for index in part.get("vertex_indices", set()))
    n_vertices = len(indices)
    payload = {"id": pid, "name": part["name"], "color": part["color"], "pivot": part["pivot"],
               "count": n_vertices, "n_vertices": n_vertices, "vertex_indices": indices,
               "is_4dgs": bool(part.get("is_4dgs", False))}
    if payload["is_4dgs"]:
        info = STATE["4dgs_parts"].get(pid, {})
        frames = info.get("frames") or []
        current_count = int(frames[0].get("n_vertices", 0)) if frames else 0
        payload.update({"n_frames_src": int(info.get("n_frames_src", 0)), "loop": bool(info.get("loop", False)),
                       "n_vertices": current_count})
    return payload


def state_summary() -> Dict[str, Any]:
    with STATE_LOCK:
        return {"loaded": STATE["loaded"], "filename": STATE["filename"], "n_vertices": STATE["n_vertices"],
                "sh_degree": int(STATE.get("sh_degree", 0)),
                "num_frames": STATE["num_frames"], "interpolation_method": STATE["interpolation_method"],
                "export_progress": STATE["export_progress"], "parts": [_serialize_part(k, v) for k, v in STATE["parts"].items()],
                "tracks": {str(k): v for k, v in STATE["tracks"].items()},
                "has_4dgs": bool(STATE["4dgs_parts"])}


def _color_for(pid: int) -> List[float]:
    return list(PART_COLORS[pid % len(PART_COLORS)])


def _workspace_has_data() -> bool:
    return int(STATE.get("n_vertices", 0)) > 0 or bool(STATE.get("4dgs_parts"))


def _empty_static_arrays() -> None:
    """Initialise the static arrays so a 4DGS-only workspace remains well-formed."""
    STATE["xyz"] = np.zeros((0, 3), dtype=np.float64)
    STATE["quats"] = np.zeros((0, 4), dtype=np.float64)
    STATE["scales"] = np.zeros((0, 3), dtype=np.float64)
    STATE["opacities"] = np.zeros(0, dtype=np.float64)
    STATE["sh0"] = np.zeros((0, 3), dtype=np.float64)
    STATE["sh_rest"] = np.zeros((0, 0, 3), dtype=np.float64)
    STATE["colors"] = np.zeros((0, 3), dtype=np.float64)
    STATE["color_valid"] = np.zeros(0, dtype=bool)
    STATE["part_id_array"] = np.zeros(0, dtype=np.int32)
    STATE["n_vertices"] = 0


def _reset_workspace() -> None:
    """Clear all editor state before an initial upload establishes a new workspace."""
    STATE.clear()
    STATE.update({
        "loaded": False, "filename": "", "n_vertices": 0, "xyz": None, "quats": None,
        "scales": None, "opacities": None, "sh0": None, "sh_rest": None, "colors": None,
        "color_valid": None, "sh_degree": 0,
        "part_id_array": None, "parts": {}, "next_part_id": 0, "tracks": {}, "num_frames": 1,
        "interpolation_method": "linear", "export_progress": -1, "export_dir": None,
        "export_done": False, "export_active": False, "4dgs_parts": {},
    })


def _normalise_static_sh_degree(target_degree: int) -> None:
    """Pad the static SH storage to the workspace-wide maximum degree."""
    n_vertices = int(STATE["n_vertices"])
    target_k = max(0, (int(target_degree) + 1) ** 2 - 1)
    STATE["sh_rest"] = _pad_sh_rest(STATE.get("sh_rest"), n_vertices, target_k)
    STATE["sh_degree"] = int(target_degree)


def _combine_static_frames(frames: List[Dict[str, Any]], target_degree: int) -> Dict[str, Any]:
    """Concatenate canonical frames after padding each SH tensor to one degree."""
    target_k = max(0, (int(target_degree) + 1) ** 2 - 1)
    n_vertices = sum(int(frame["n_vertices"]) for frame in frames)
    source_colors = []
    source_color_valid = []
    for frame in frames:
        count = int(frame["n_vertices"])
        colors = _normalise_rgb(frame.get("colors"), count)
        source_colors.append(colors if colors is not None else np.zeros((count, 3), dtype=np.float64))
        valid = frame.get("color_valid")
        if valid is None:
            valid = np.full(count, bool(frame.get("has_colors", False)), dtype=bool)
        source_color_valid.append(np.asarray(valid, dtype=bool).reshape(count))
    return {
        "xyz": np.concatenate([frame["xyz"] for frame in frames], axis=0),
        "quats": np.concatenate([frame["quats"] for frame in frames], axis=0),
        "scales": np.concatenate([frame["scales"] for frame in frames], axis=0),
        "opacities": np.concatenate([frame["opacities"] for frame in frames], axis=0),
        "sh0": np.concatenate([frame["sh0"] for frame in frames], axis=0),
        "sh_rest": np.concatenate([_pad_sh_rest(frame.get("sh_rest"), frame["n_vertices"], target_k) for frame in frames], axis=0),
        "sh_degree": int(target_degree),
        "n_vertices": n_vertices,
        "colors": np.concatenate(source_colors, axis=0),
        "color_valid": np.concatenate(source_color_valid, axis=0),
    }


def _static_frame_from_state() -> Dict[str, Any]:
    return {key: STATE[key] for key in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "sh_degree", "n_vertices", "colors", "color_valid")}


def _remove_static_indices_from_parts(indices: List[int]) -> None:
    for part in STATE["parts"].values():
        if not part.get("is_4dgs", False):
            part.get("vertex_indices", set()).difference_update(indices)


def _delete_static_vertices(indices: List[int]) -> int:
    """Physically remove static vertices and remap every remaining Part index."""
    count = int(STATE.get("n_vertices", 0))
    deleted = sorted({int(index) for index in indices if 0 <= int(index) < count})
    if not deleted:
        return 0

    keep = np.ones(count, dtype=bool)
    keep[deleted] = False
    old_to_new = np.full(count, -1, dtype=np.int32)
    old_to_new[keep] = np.arange(int(np.count_nonzero(keep)), dtype=np.int32)

    for field in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "colors", "color_valid", "part_id_array"):
        values = STATE.get(field)
        if values is not None:
            STATE[field] = np.asarray(values)[keep]
    for part in STATE["parts"].values():
        if part.get("is_4dgs", False):
            continue
        part["vertex_indices"] = {
            int(old_to_new[index]) for index in part.get("vertex_indices", set())
            if 0 <= int(index) < count and old_to_new[int(index)] >= 0
        }
    STATE["n_vertices"] = int(np.count_nonzero(keep))
    return len(deleted)


def _refresh_static_part_pivot(pid: int) -> List[float]:
    part = STATE["parts"][pid]
    indices = sorted(part.get("vertex_indices", set()))
    if not indices or STATE["xyz"] is None:
        raise ValueError("Part has no static vertices")
    pivot = np.mean(STATE["xyz"][indices], axis=0).astype(float).tolist()
    part["pivot"] = pivot
    return pivot


def _valid_static_indices(raw_indices: Any) -> List[int]:
    if not isinstance(raw_indices, list):
        raise ValueError("vertex_indices must be a list")
    if STATE["n_vertices"] <= 0:
        return []
    return sorted({int(index) for index in raw_indices if 0 <= int(index) < STATE["n_vertices"]})


def _key_rotation(key: Dict[str, float]) -> Tuple[np.ndarray, np.ndarray]:
    rx, ry, rz = [float(key.get(k, 0)) for k in ("rx", "ry", "rz")]
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    R = np.array([[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx], [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx], [-sy, cy*sx, cy*cx]])
    # Same ZYX convention as the rotation matrix above, stored as wxyz.
    q = np.array([math.cos(rz/2)*math.cos(ry/2)*math.cos(rx/2) + math.sin(rz/2)*math.sin(ry/2)*math.sin(rx/2),
                  math.cos(rz/2)*math.cos(ry/2)*math.sin(rx/2) - math.sin(rz/2)*math.sin(ry/2)*math.cos(rx/2),
                  math.cos(rz/2)*math.sin(ry/2)*math.cos(rx/2) + math.sin(rz/2)*math.cos(ry/2)*math.sin(rx/2),
                  math.sin(rz/2)*math.cos(ry/2)*math.cos(rx/2) - math.cos(rz/2)*math.sin(ry/2)*math.sin(rx/2)])
    return R, q


def _transform_xyz(xyz: np.ndarray, pivot: List[float], key: Dict[str, float]) -> np.ndarray:
    p = np.asarray(pivot, dtype=np.float64)
    t = np.asarray([key.get("tx", 0), key.get("ty", 0), key.get("tz", 0)], dtype=np.float64)
    R, _ = _key_rotation(key)
    return (xyz - p) @ R.T + p + t


def _clean_scale(value: Any = 1.0) -> float:
    """Validate a positive global point-cloud scale from a public request."""
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("scale must be a number") from exc
    if not np.isfinite(scale) or scale <= 0 or scale > 100:
        raise ValueError("scale must be finite, greater than 0, and at most 100")
    return scale


def _resolve_user_path(value: str) -> str:
    """Resolve a path entered in the UI to the server's local absolute path.

    ``expanduser`` handles Linux inputs such as ``~/Desktop/delete`` and
    ``expandvars`` handles common ``$HOME``/``%USERPROFILE%`` forms.
    """
    return os.path.abspath(os.path.expanduser(os.path.expandvars(value.strip())))


def _scale_xyz_about_centroid(xyz: np.ndarray, scale: float) -> np.ndarray:
    """Scale XYZ around its own centroid without mutating the input array."""
    points = np.asarray(xyz, dtype=np.float64).reshape((-1, 3))
    if len(points) == 0 or scale == 1.0:
        return points.copy()
    pivot = np.mean(points, axis=0)
    return (points - pivot) * float(scale) + pivot


def _rotate_quats(quats: np.ndarray, key: Dict[str, float]) -> np.ndarray:
    """Apply the Part's Euler rotation to wxyz source quaternions."""
    _, r = _key_rotation(key)
    q = np.asarray(quats, dtype=np.float64)
    if len(q) == 0:
        return q.copy()
    w1, x1, y1, z1 = r
    w2, x2, y2, z2 = q.T
    out = np.column_stack((w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2,
                           w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2))
    norm = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(norm, 1e-12)


def _key_for(pid: int, frame: int) -> Dict[str, float]:
    keys = sorted(STATE["tracks"].get(pid, []), key=lambda x: x["frame"])
    return interpolate_keyframes(keys, frame, STATE["interpolation_method"])


def _write_pt(path: str, frame: Dict[str, Any]) -> None:
    save_frame_as_pt(frame["xyz"], frame["quats"], frame["scales"], frame["opacities"], frame["sh0"], frame.get("sh_rest"), frame.get("sh_degree", 0), path, colors=frame.get("colors"))


def compute_frame_data(frame: int) -> Tuple[np.ndarray, np.ndarray]:
    """Compute transformed static arrays from the immutable STATE source data."""
    xyz = np.array(STATE["xyz"], dtype=np.float64, copy=True) if STATE["xyz"] is not None else np.zeros((0, 3))
    quats = np.array(STATE["quats"], dtype=np.float64, copy=True) if STATE["quats"] is not None else np.zeros((len(xyz), 4))
    for pid, part in STATE["parts"].items():
        if part.get("is_4dgs"):
            continue
        indices = sorted(part.get("vertex_indices", set()))
        if indices:
            xyz[indices], quats[indices] = _apply_transform_to_data(xyz[indices], quats[indices], part["pivot"], _key_for(pid, frame))
    return xyz, quats


def compute_full_frame_data(frame: int, apply_transforms: bool = True) -> Dict[str, Any]:
    """Build one frame, padding SH rest coefficients across all sources."""
    data = frame_data(frame, apply_transforms=apply_transforms)
    max_degree = max(int(data.get("sh_degree", 0)), 0); target_k = max(0, (max_degree + 1) ** 2 - 1)
    data["sh_rest"] = _pad_sh_rest(data.get("sh_rest"), len(data["xyz"]), target_k)
    data["sh_degree"] = max_degree; data["n_vertices"] = len(data["xyz"]); data["part_id_array"] = data.get("part_ids")
    return data


def frame_data(frame: int, apply_transforms: bool = True) -> Dict[str, Any]:
    with STATE_LOCK:
        xyzs, quats, scales, opacities, sh0s, rests, cols, original_cols, ids, source_indices = [], [], [], [], [], [], [], [], [], []
        claimed_static = np.zeros(int(STATE.get("n_vertices", 0)), dtype=bool)
        for pid, part in STATE["parts"].items():
            if part.get("is_4dgs"):
                info = STATE["4dgs_parts"].get(pid); src = info["frames"][_get_4dgs_frame_idx(pid, frame)] if info and info["frames"] else None
                if src is None: continue
                idx = None
            else:
                idx = sorted(part.get("vertex_indices", set()))
                if not idx or STATE["xyz"] is None: continue
                claimed_static[idx] = True
                src = {k: STATE[k][idx] if STATE[k] is not None else None
                       for k in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "colors", "color_valid")}
                src["sh_degree"] = STATE["sh_degree"]
            key = _key_for(pid, frame) if apply_transforms else {"tx": 0.0, "ty": 0.0, "tz": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
            xyzs.append(_transform_xyz(src["xyz"], part["pivot"], key)); quats.append(_rotate_quats(src["quats"], key))
            scales.append(src["scales"]); opacities.append(src["opacities"]); sh0s.append(src["sh0"])
            rests.append(src.get("sh_rest")); cols.append(np.tile(part["color"], (len(src["xyz"]), 1))); original_cols.append(_original_colors(src)); ids.append(np.full(len(src["xyz"]), pid))
            source_indices.append(np.asarray(idx, dtype=np.int32) if idx is not None else np.full(len(src["xyz"]), -1))
        # Deleted or never-assigned static vertices remain part of the point cloud.
        # Keep them in frame/export responses with their source SH-derived color.
        if STATE["xyz"] is not None and len(claimed_static):
            unassigned = np.flatnonzero(~claimed_static)
            if len(unassigned):
                src = {k: STATE[k][unassigned] if STATE[k] is not None else None
                       for k in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "colors", "color_valid")}
                src["sh_degree"] = STATE["sh_degree"]
                identity = {"tx": 0.0, "ty": 0.0, "tz": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
                xyzs.append(_transform_xyz(src["xyz"], [0.0, 0.0, 0.0], identity) if apply_transforms else src["xyz"])
                quats.append(src["quats"]); scales.append(src["scales"]); opacities.append(src["opacities"])
                sh0s.append(src["sh0"]); rests.append(src.get("sh_rest")); cols.append(_original_colors(src)); original_cols.append(_original_colors(src))
                ids.append(np.full(len(unassigned), -1, dtype=np.int32)); source_indices.append(unassigned.astype(np.int32))
        if not xyzs:
            return {"xyz": np.zeros((0,3)), "quats": np.zeros((0,4)), "scales": np.zeros((0,3)), "opacities": np.zeros(0),
                    "sh0": np.zeros((0,3)), "sh_rest": None, "sh_degree": 0, "colors": np.zeros((0,3)), "original_colors": np.zeros((0,3)), "part_ids": np.zeros(0, dtype=np.int32), "source_indices": np.zeros(0, dtype=np.int32), "frame": frame}
        max_degree = max([STATE["sh_degree"]] + [STATE["4dgs_parts"][p]["sh_degree"] for p in STATE["4dgs_parts"]])
        target_k = max(0, (max_degree + 1) ** 2 - 1)
        combined_rest = np.concatenate([_pad_sh_rest(r, len(xyzs[i]), target_k) for i, r in enumerate(rests)], axis=0) if target_k else np.zeros((sum(len(x) for x in xyzs), 0, 3), dtype=np.float64)
        return {"xyz": np.concatenate(xyzs), "quats": np.concatenate(quats), "scales": np.concatenate(scales), "opacities": np.concatenate(opacities),
                "sh0": np.concatenate(sh0s), "sh_rest": combined_rest, "sh_degree": max_degree,
                "colors": np.concatenate(cols), "original_colors": np.concatenate(original_cols), "part_ids": np.concatenate(ids), "source_indices": np.concatenate(source_indices), "frame": frame}


def frame_payload(frame: int) -> Dict[str, Any]:
    data = frame_data(frame)
    return {"xyz": data["xyz"].astype(float).tolist(), "colors": data["colors"].astype(float).tolist(),
            "part_ids": data["part_ids"].astype(int).tolist(), "source_indices": data["source_indices"].astype(int).tolist(), "frame": frame}


def _raw_pointcloud_arrays(frame: int = 0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return source positions, display colors, and Part ids without keyframe transforms."""
    static_xyz = np.asarray(STATE["xyz"], dtype=np.float64) if STATE["xyz"] is not None else np.zeros((0, 3), dtype=np.float64)
    static_sh0 = np.asarray(STATE["sh0"], dtype=np.float64) if STATE["sh0"] is not None else np.zeros((len(static_xyz), 3), dtype=np.float64)
    static_ids = np.asarray(STATE["part_id_array"], dtype=np.int32) if STATE["part_id_array"] is not None else np.full(len(static_xyz), -1, dtype=np.int32)
    colors = sh_to_rgb(static_sh0)
    if len(colors) != len(static_xyz):
        colors = np.zeros((len(static_xyz), 3), dtype=np.float64)
    xyz_chunks, color_chunks, id_chunks = [static_xyz], [colors], [static_ids]
    for pid, part in STATE["parts"].items():
        if not part.get("is_4dgs", False):
            continue
        info = STATE["4dgs_parts"].get(pid)
        if not info or not info.get("frames"):
            continue
        source_frame = info["frames"][_get_4dgs_frame_idx(pid, frame)]
        count = int(source_frame["n_vertices"])
        xyz_chunks.append(np.asarray(source_frame["xyz"], dtype=np.float64))
        color_chunks.append(np.tile(np.asarray(part["color"], dtype=np.float64), (count, 1)))
        id_chunks.append(np.full(count, pid, dtype=np.int32))
    return np.concatenate(xyz_chunks, axis=0), np.concatenate(color_chunks, axis=0), np.concatenate(id_chunks, axis=0)


def _comparison_colors(source: Dict[str, Any]) -> np.ndarray:
    """Return explicit RGB when available, otherwise SH-derived or neutral gray."""
    colors = source.get("colors") if source.get("has_colors") else None
    if colors is not None:
        normalised = _normalise_rgb(colors, int(source.get("n_vertices", 0)))
        if normalised is not None and np.isfinite(normalised).all():
            return normalised
    try:
        sh0 = np.asarray(source.get("sh0"), dtype=np.float64)
    except (TypeError, ValueError):
        sh0 = np.zeros((0, 3), dtype=np.float64)
    if sh0.shape == (int(source.get("n_vertices", 0)), 3):
        derived = sh_to_rgb(sh0)
        if np.isfinite(derived).all():
            return derived
    return np.full((int(source.get("n_vertices", 0)), 3), 0.5, dtype=np.float64)


def _comparison_source_arrays(source: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """Validate and return finite Comparison XYZ/RGB arrays."""
    try:
        xyz = np.asarray(source.get("xyz"), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("Comparison point clouds must have shape (N, 3)") from exc
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("Comparison point clouds must have shape (N, 3)")
    if not np.isfinite(xyz).all():
        raise ValueError("Comparison XYZ coordinates must be finite")
    colors = np.asarray(_comparison_colors({**source, "n_vertices": len(xyz)}), dtype=np.float64)
    if colors.shape != (len(xyz), 3) or not np.isfinite(colors).all():
        raise ValueError("Comparison RGB colors must be finite")
    return xyz, colors


def _comparison_default_sor_state() -> Dict[str, Any]:
    return {
        "enabled": False,
        "neighbors": int(_COMPARISON_SOR_DEFAULTS["neighbors"]),
        "stddev_multiplier": float(_COMPARISON_SOR_DEFAULTS["stddev_multiplier"]),
        "effective_neighbors": None,
        "threshold": None,
        "original_n_vertices": 0,
        "n_vertices": 0,
        "removed_vertices": 0,
    }


def _comparison_active_arrays(info: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """Return the currently active Comparison XYZ/RGB arrays."""
    xyz, colors = _comparison_source_arrays(info["source"])
    indices = info.get("active_indices")
    if indices is None:
        return xyz, colors
    indices = np.asarray(indices, dtype=np.int64)
    return xyz[indices], colors[indices]


def _clean_comparison_sor_parameters(value: Any) -> Tuple[int, float]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("SOR cloud parameters must be an object")
    raw_neighbors = value.get("neighbors", _COMPARISON_SOR_DEFAULTS["neighbors"])
    try:
        neighbors_number = float(raw_neighbors)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("SOR neighbors must be a finite integer >= 1") from exc
    if not np.isfinite(neighbors_number) or neighbors_number < 1 or not neighbors_number.is_integer():
        raise ValueError("SOR neighbors must be a finite integer >= 1")
    raw_multiplier = value.get("stddev_multiplier", _COMPARISON_SOR_DEFAULTS["stddev_multiplier"])
    try:
        stddev_multiplier = float(raw_multiplier)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("SOR stddev_multiplier must be a finite number >= 0") from exc
    if not np.isfinite(stddev_multiplier) or stddev_multiplier < 0:
        raise ValueError("SOR stddev_multiplier must be a finite number >= 0")
    return int(neighbors_number), stddev_multiplier


def _comparison_knn_mean_distances(points: np.ndarray, neighbors: int, source_block_size: int = 512,
                                   target_block_size: int = 4096) -> Tuple[np.ndarray, int]:
    """Return each point's mean distance to its K same-cloud neighbours."""
    points = np.asarray(points, dtype=np.float64).reshape((-1, 3))
    if len(points) < 2:
        return np.zeros(len(points), dtype=np.float64), 0
    effective_neighbors = min(int(neighbors), len(points) - 1)
    means = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), source_block_size):
        stop = min(start + source_block_size, len(points))
        block = points[start:stop]
        block_size = stop - start
        best_squared = np.full((block_size, effective_neighbors), np.inf, dtype=np.float64)
        row_indices = np.arange(start, stop)
        block_sq = np.sum(block * block, axis=1)[:, None]
        for target_start in range(0, len(points), target_block_size):
            target_stop = min(target_start + target_block_size, len(points))
            target_block = points[target_start:target_stop]
            squared = block_sq + np.sum(target_block * target_block, axis=1)[None, :]
            squared -= 2.0 * block @ target_block.T
            squared = np.maximum(squared, 0.0)
            local_rows = row_indices - target_start
            inside = (local_rows >= 0) & (local_rows < len(target_block))
            squared[np.flatnonzero(inside), local_rows[inside]] = np.inf
            take = min(effective_neighbors, len(target_block))
            local = np.argpartition(squared, take - 1, axis=1)[:, :take]
            local_squared = np.take_along_axis(squared, local, axis=1)
            combined = np.concatenate((best_squared, local_squared), axis=1)
            best = np.argpartition(combined, effective_neighbors - 1, axis=1)[:, :effective_neighbors]
            best_squared = np.take_along_axis(combined, best, axis=1)
        means[start:stop] = np.mean(np.sqrt(best_squared), axis=1)
    return means, effective_neighbors


def _comparison_sor_filter(points: np.ndarray, neighbors: int, stddev_multiplier: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Compute a standard Statistical Outlier Removal mask for one cloud."""
    points = np.asarray(points, dtype=np.float64).reshape((-1, 3))
    count = len(points)
    mean_distances, effective_neighbors = _comparison_knn_mean_distances(points, neighbors)
    if count < 2:
        return np.ones(count, dtype=bool), {
            "effective_neighbors": 0,
            "threshold": None,
            "mean_distance": None,
            "std_distance": None,
        }
    mean_distance = float(np.mean(mean_distances))
    std_distance = float(np.std(mean_distances))
    threshold = mean_distance + float(stddev_multiplier) * std_distance
    mask = np.isfinite(mean_distances) & (mean_distances <= threshold)
    if not np.any(mask):
        mask = np.ones(count, dtype=bool)
    return mask, {
        "effective_neighbors": effective_neighbors,
        "threshold": threshold,
        "mean_distance": mean_distance,
        "std_distance": std_distance,
    }


def _comparison_sor_metadata(cloud_id: str, info: Dict[str, Any]) -> Dict[str, Any]:
    sor = dict(info.get("sor") or _comparison_default_sor_state())
    original_n = int(info.get("original_n_vertices", info.get("n_vertices", 0)))
    active_indices = info.get("active_indices")
    active_n = original_n if active_indices is None else int(len(active_indices))
    sor.update({
        "original_n_vertices": original_n,
        "n_vertices": active_n,
        "removed_vertices": original_n - active_n,
    })
    return {
        "id": cloud_id,
        "filename": info["filename"],
        "n_vertices": active_n,
        "original_n_vertices": original_n,
        "removed_vertices": original_n - active_n,
        "has_colors": bool(info.get("has_colors", False)),
        "sor": sor,
    }


@app.get("/")
def index():
    editor_path = os.path.join(BASE_DIR, "static", "editor.html")
    if os.path.isfile(editor_path):
        with open(editor_path, "r", encoding="utf-8") as handle:
            return handle.read()
    return HTML_PAGE

@app.get("/api/state")
def api_state(): return jsonify(state_summary())

@app.get("/api/frame/<int:frame>")
def api_frame(frame):
    """Return an untransformed frame in the legacy/static or full 4DGS binary format."""
    with STATE_LOCK:
        if not _workspace_has_data():
            return jsonify({"error": "No point-cloud data is loaded"}), 400
        frame = max(0, min(int(frame), max(0, STATE["num_frames"] - 1)))
        xyz, colors, part_ids = _raw_pointcloud_arrays(frame)
        has_4dgs = bool(STATE["4dgs_parts"])
    buf = io.BytesIO()
    xyz = np.asarray(xyz, dtype="<f4")
    buf.write(struct.pack("<I", int(len(xyz))))
    buf.write(xyz.tobytes(order="C"))
    if has_4dgs:
        buf.write(np.asarray(colors, dtype="<f4").tobytes(order="C"))
        buf.write(np.asarray(part_ids, dtype="<i4").tobytes(order="C"))
    return Response(buf.getvalue(), mimetype="application/octet-stream")

@app.post("/api/upload")
def api_upload():
    files = request.files.getlist("file")
    if not files:
        files = request.files.getlist("files")  # Compatibility with the existing browser UI.
    if not files: return jsonify({"error": "没有收到文件"}), 400
    parsed_files = []
    upload_dir = tempfile.mkdtemp(prefix="upload_", dir=UPLOAD_ROOT)
    try:
        for uploaded in files:
            filename = os.path.basename(uploaded.filename or "")
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_POINTCLOUD_EXTENSIONS:
                return jsonify({"error": f"Unsupported file type: {filename or '<unnamed>'}"}), 400
            upload_path = os.path.join(upload_dir, filename)
            uploaded.save(upload_path)
            parsed_files.append((filename, _load_pointcloud_path(upload_path, ext)))
    except Exception as exc: return jsonify({"error": str(exc)}), 400
    if not parsed_files: return jsonify({"error": "没有有效的 .ply、.pt 或 .npy 文件"}), 400
    first = parsed_files[0][0]
    parsed = {}
    parsed["xyz"] = np.concatenate([p["xyz"] for _, p in parsed_files], axis=0)
    parsed["quats"] = np.concatenate([p["quats"] for _, p in parsed_files], axis=0)
    parsed["scales"] = np.concatenate([p["scales"] for _, p in parsed_files], axis=0)
    parsed["opacities"] = np.concatenate([p["opacities"] for _, p in parsed_files], axis=0)
    parsed["sh0"] = np.concatenate([p["sh0"] for _, p in parsed_files], axis=0)
    parsed["sh_degree"] = max(p["sh_degree"] for _, p in parsed_files)
    parsed["sh_rest"] = np.concatenate([_pad_sh_rest(p.get("sh_rest"), p["n_vertices"], max(0, (parsed["sh_degree"] + 1) ** 2 - 1)) for _, p in parsed_files], axis=0)
    parsed["n_vertices"] = len(parsed["xyz"])
    parsed["colors"] = np.concatenate([_original_colors(source) for _, source in parsed_files], axis=0)
    parsed["color_valid"] = np.concatenate([np.full(source["n_vertices"], bool(source.get("has_colors", False)), dtype=bool) for _, source in parsed_files], axis=0)
    with STATE_LOCK:
        _reset_workspace()
        for key in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "colors", "color_valid"): STATE[key] = parsed[key]
        STATE["sh_degree"], STATE["n_vertices"], STATE["filename"], STATE["loaded"] = parsed["sh_degree"], parsed["n_vertices"], first, True
        STATE["part_id_array"] = np.full(parsed["n_vertices"], -1, dtype=np.int32); STATE["parts"].clear(); STATE["tracks"].clear(); STATE["4dgs_parts"].clear(); STATE["next_part_id"] = 0
        offset = 0
        parts_created = []
        for filename, source in parsed_files:
            count = source["n_vertices"]
            pid = STATE["next_part_id"]; STATE["next_part_id"] += 1
            indices = set(range(offset, offset + count))
            STATE["parts"][pid] = {"name": os.path.splitext(filename)[0], "color": _color_for(pid),
                                    "pivot": np.mean(parsed["xyz"][offset:offset + count], axis=0).tolist() if count else [0, 0, 0],
                                    "vertex_indices": indices}
            STATE["part_id_array"][list(indices)] = pid
            STATE["tracks"][pid] = []
            parts_created.append(_serialize_part(pid, STATE["parts"][pid]))
            offset += count
    return jsonify({"ok": True, "filename": STATE["filename"], "n_vertices": STATE["n_vertices"],
                    "sh_degree": STATE["sh_degree"], "parts_created": parts_created, "n_files": len(parsed_files)})

def _load_uploaded_pointclouds(uploaded_files) -> List[Tuple[str, Dict[str, Any]]]:
    """Save incoming files under the temporary upload root and load canonical point clouds."""
    upload_dir = tempfile.mkdtemp(prefix="upload_", dir=UPLOAD_ROOT)
    parsed_files = []
    for sequence, uploaded in enumerate(uploaded_files):
        filename = os.path.basename(uploaded.filename or "")
        extension = os.path.splitext(filename)[1].lower()
        if not filename or extension not in SUPPORTED_POINTCLOUD_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {filename or '<unnamed>'}")
        saved_name = filename if not os.path.exists(os.path.join(upload_dir, filename)) else f"{sequence}_{filename}"
        saved_path = os.path.join(upload_dir, saved_name)
        uploaded.save(saved_path)
        parsed_files.append((filename, _load_pointcloud_path(saved_path, extension)))
    if not parsed_files:
        raise ValueError("No .ply, .pt, or .npy files were provided")
    return parsed_files


@app.post("/api/upload_append")
def api_upload_append():
    files = request.files.getlist("file")
    if not files:
        files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files were provided"}), 400
    try:
        parsed_files = _load_uploaded_pointclouds(files)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    with STATE_LOCK:
        if not STATE["loaded"] or STATE["xyz"] is None or int(STATE.get("n_vertices", 0)) <= 0:
            return jsonify({"error": "Upload a base point cloud before appending"}), 400
        previous_count = int(STATE["n_vertices"])
        target_degree = max([int(STATE["sh_degree"])] + [int(source["sh_degree"]) for _, source in parsed_files])
        combined = _combine_static_frames([_static_frame_from_state()] + [source for _, source in parsed_files], target_degree)
        for key in ("xyz", "quats", "scales", "opacities", "sh0", "sh_rest", "colors", "color_valid"):
            STATE[key] = combined[key]
        STATE["n_vertices"] = combined["n_vertices"]
        STATE["sh_degree"] = target_degree
        old_ids = STATE["part_id_array"] if STATE["part_id_array"] is not None else np.full(previous_count, -1, dtype=np.int32)
        STATE["part_id_array"] = np.concatenate((old_ids.astype(np.int32, copy=False), np.full(combined["n_vertices"] - previous_count, -1, dtype=np.int32)))
        parts_created = []
        offset = previous_count
        for filename, source in parsed_files:
            count = int(source["n_vertices"])
            pid = STATE["next_part_id"]
            STATE["next_part_id"] += 1
            indices = set(range(offset, offset + count))
            STATE["parts"][pid] = {"name": os.path.splitext(filename)[0], "color": _color_for(pid),
                                    "pivot": np.mean(STATE["xyz"][offset:offset + count], axis=0).tolist() if count else [0, 0, 0],
                                    "vertex_indices": indices}
            if indices:
                STATE["part_id_array"][list(indices)] = pid
            STATE["tracks"][pid] = []
            parts_created.append(_serialize_part(pid, STATE["parts"][pid]))
            offset += count
    return jsonify({"ok": True, "n_vertices_added": combined["n_vertices"] - previous_count,
                    "n_vertices": combined["n_vertices"], "sh_degree": target_degree,
                    "parts_created": parts_created, "n_files": len(parsed_files)})


@app.post("/api/upload_4dgs")
def api_upload_4dgs():
    body = request.get_json(silent=True) or {}
    dir_path = body.get("dir_path")
    if not isinstance(dir_path, str) or not dir_path:
        return jsonify({"error": "dir_path is required"}), 400
    try:
        source = load_4dgs_dir(dir_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    with STATE_LOCK:
        if STATE["xyz"] is None:
            _empty_static_arrays()
        source_degree = int(source["sh_degree"])
        workspace_degree = max(int(STATE["sh_degree"]), source_degree)
        _normalise_static_sh_degree(workspace_degree)
        target_k = max(0, (workspace_degree + 1) ** 2 - 1)
        for source_frame in source["frames"]:
            source_frame["sh_rest"] = _pad_sh_rest(source_frame.get("sh_rest"), source_frame["n_vertices"], target_k)
            source_frame["sh_degree"] = workspace_degree
        pid = STATE["next_part_id"]
        STATE["next_part_id"] += 1
        first_frame = source["frames"][0]
        STATE["parts"][pid] = {"name": str(body.get("name") or f"4DGS Part {pid}"), "color": _color_for(pid),
                                "pivot": np.mean(first_frame["xyz"], axis=0).tolist() if first_frame["n_vertices"] else [0, 0, 0],
                                "vertex_indices": set(), "is_4dgs": True}
        STATE["4dgs_parts"][pid] = {**source, "sh_degree": workspace_degree, "loop": bool(body.get("loop", False))}
        STATE["tracks"][pid] = []
        STATE["sh_degree"] = workspace_degree
        STATE["loaded"] = True
        if not STATE["filename"]:
            STATE["filename"] = os.path.basename(os.path.normpath(dir_path))
        part_payload = _serialize_part(pid, STATE["parts"][pid])
    return jsonify({"ok": True, "part": part_payload, "n_frames_src": source["n_frames_src"],
                    "n_vertices": first_frame["n_vertices"], "filenames": source["filenames"]})


@app.get("/api/pointcloud")
def api_pointcloud():
    try:
        frame = max(0, int(request.args.get("frame", "0")))
    except ValueError:
        return jsonify({"error": "frame must be an integer"}), 400
    with STATE_LOCK:
        if not _workspace_has_data():
            return jsonify({"error": "No point-cloud data is loaded"}), 400
        xyz, colors, part_ids = _raw_pointcloud_arrays(frame)
        for pid, part in STATE["parts"].items():
            if not part.get("is_4dgs", False):
                colors[part_ids == pid] = np.asarray(part["color"], dtype=np.float64)
    buf = io.BytesIO()
    buf.write(struct.pack("<I", int(len(xyz))))
    buf.write(np.asarray(xyz, dtype="<f4").tobytes(order="C"))
    buf.write(np.asarray(colors, dtype="<f4").tobytes(order="C"))
    buf.write(np.asarray(part_ids, dtype="<i4").tobytes(order="C"))
    buf.seek(0)
    return Response(buf.read(), mimetype="application/octet-stream")


@app.post("/api/comparison")
def api_comparison_upload():
    """Create an isolated two-cloud comparison session."""
    files = request.files.getlist("files")
    if not files:
        files = request.files.getlist("file")
    if len(files) != 2:
        return jsonify({"error": "Comparison requires exactly two .ply, .pt, or .npy files"}), 400

    parsed = []
    try:
        for uploaded in files:
            filename = os.path.basename(uploaded.filename or "")
            extension = os.path.splitext(filename)[1].lower()
            if not filename or extension not in SUPPORTED_POINTCLOUD_EXTENSIONS:
                raise ValueError(f"Unsupported file type: {filename or '<unnamed>'}")
            payload = uploaded.read()
            if not payload:
                raise ValueError(f"Empty point-cloud file: {filename}")
            source = _load_pointcloud_bytes(payload, extension)
            xyz, _ = _comparison_source_arrays(source)
            if len(xyz) <= 0:
                raise ValueError(f"Point-cloud file has no vertices: {filename}")
            parsed.append((filename, source))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    with STATE_LOCK:
        COMPARISON_STATE["clouds"] = {
            cloud_id: {
                "filename": filename,
                "source": source,
                "original_n_vertices": int(source["n_vertices"]),
                "active_indices": None,
                "has_colors": bool(source.get("has_colors", False)),
                "sor": _comparison_default_sor_state(),
            }
            for cloud_id, (filename, source) in zip(("a", "b"), parsed)
        }
        clouds = [_comparison_sor_metadata(cloud_id, info)
                  for cloud_id, info in COMPARISON_STATE["clouds"].items()]
    return jsonify({"ok": True, "clouds": clouds})


@app.get("/api/comparison/<any(a,b):cloud_id>")
def api_comparison_cloud(cloud_id: str):
    if cloud_id not in ("a", "b"):
        return jsonify({"error": "cloud_id must be 'a' or 'b'"}), 400
    with STATE_LOCK:
        info = COMPARISON_STATE["clouds"].get(cloud_id)
        if not info:
            return jsonify({"error": "No comparison session is loaded"}), 400
        source = info["source"]
        try:
            xyz, colors = _comparison_active_arrays(info)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        xyz = np.asarray(xyz, dtype="<f4")
        colors = np.asarray(colors, dtype="<f4")
    if len(xyz) != len(colors):
        return jsonify({"error": "Comparison point-cloud color length mismatch"}), 500
    buf = io.BytesIO()
    buf.write(struct.pack("<I", int(len(xyz))))
    buf.write(xyz.tobytes(order="C"))
    buf.write(colors.tobytes(order="C"))
    return Response(buf.getvalue(), mimetype="application/octet-stream")


@app.delete("/api/comparison")
def api_comparison_delete():
    with STATE_LOCK:
        COMPARISON_STATE["clouds"] = {"a": None, "b": None}
    return jsonify({"ok": True})


@app.post("/api/comparison/sor")
def api_comparison_sor():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("clouds"), dict):
        return jsonify({"error": "clouds must be an object"}), 400
    try:
        parameters = {
            cloud_id: _clean_comparison_sor_parameters(body["clouds"].get(cloud_id))
            for cloud_id in ("a", "b")
        }
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with STATE_LOCK:
        if not COMPARISON_STATE["clouds"].get("a") or not COMPARISON_STATE["clouds"].get("b"):
            return jsonify({"error": "Load both comparison point clouds before applying SOR"}), 400
        results = {}
        computed = {}
        try:
            for cloud_id, (neighbors, stddev_multiplier) in parameters.items():
                info = COMPARISON_STATE["clouds"][cloud_id]
                source_xyz, _ = _comparison_source_arrays(info["source"])
                mask, details = _comparison_sor_filter(source_xyz, neighbors, stddev_multiplier)
                active_indices = np.flatnonzero(mask).astype(np.int64, copy=False)
                computed[cloud_id] = (active_indices, {
                    "enabled": True,
                    "neighbors": neighbors,
                    "stddev_multiplier": stddev_multiplier,
                    "effective_neighbors": int(details["effective_neighbors"]),
                    "threshold": details["threshold"],
                    "mean_distance": details["mean_distance"],
                    "std_distance": details["std_distance"],
                    "original_n_vertices": int(len(source_xyz)),
                    "n_vertices": int(len(active_indices)),
                    "removed_vertices": int(len(source_xyz) - len(active_indices)),
                })
            for cloud_id, (active_indices, sor_state) in computed.items():
                info = COMPARISON_STATE["clouds"][cloud_id]
                info["active_indices"] = active_indices
                info["sor"] = sor_state
                results[cloud_id] = _comparison_sor_metadata(cloud_id, info)
        except (TypeError, ValueError, MemoryError) as exc:
            return jsonify({"error": f"Unable to apply SOR: {exc}"}), 400
    return jsonify({"ok": True, "clouds": results})


@app.delete("/api/comparison/sor")
def api_comparison_sor_reset():
    with STATE_LOCK:
        for info in COMPARISON_STATE["clouds"].values():
            if not info:
                continue
            info["active_indices"] = None
            info["sor"] = _comparison_default_sor_state()
        clouds = {
            cloud_id: _comparison_sor_metadata(cloud_id, info)
            for cloud_id, info in COMPARISON_STATE["clouds"].items()
            if info
        }
    return jsonify({"ok": True, "clouds": clouds})


def _clean_comparison_export_transform(value: Any) -> Dict[str, float]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("transform must be an object")
    transform: Dict[str, float] = {}
    for name in ("tx", "ty", "tz", "rx", "ry", "rz"):
        try:
            number = float(value.get(name, 0.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"transform.{name} must be a finite number") from exc
        if not np.isfinite(number):
            raise ValueError(f"transform.{name} must be a finite number")
        transform[name] = number
    transform["scale"] = _clean_scale(value.get("scale", 1.0))
    return transform


def _comparison_ply_bytes(points: np.ndarray, colors: np.ndarray) -> bytes:
    points = np.asarray(points, dtype=np.float32).reshape((-1, 3))
    colors_u8 = np.rint(np.clip(colors, 0.0, 1.0) * 255.0).astype(np.uint8).reshape((-1, 3))
    vertices = np.empty(len(points), dtype=[
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("red", "u1"), ("green", "u1"), ("blue", "u1"),
    ])
    vertices["x"], vertices["y"], vertices["z"] = points.T
    vertices["red"], vertices["green"], vertices["blue"] = colors_u8.T
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(points)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    return header + vertices.tobytes(order="C")


@app.post("/api/comparison/export")
def api_comparison_export():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    cloud_id = str(body.get("cloud_id", "")).strip().lower()
    export_format = str(body.get("format", "")).strip().lower().lstrip(".")
    if cloud_id not in ("a", "b"):
        return jsonify({"error": "cloud_id must be 'a' or 'b'"}), 400
    if export_format not in ("ply", "pt", "npy"):
        return jsonify({"error": "format must be 'ply', 'pt', or 'npy'"}), 400
    try:
        transform = _clean_comparison_export_transform(body.get("transform"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with STATE_LOCK:
        info = COMPARISON_STATE["clouds"].get(cloud_id)
        if not info:
            return jsonify({"error": "No comparison session is loaded"}), 400
        source = info["source"]
        try:
            source_xyz, colors = _comparison_source_arrays(source)
            points = _comparison_transformed_xyz({**source, "xyz": source_xyz}, transform)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        source_filename = str(info.get("filename") or f"cloud_{cloud_id}")

    if len(points) != len(colors):
        return jsonify({"error": "Comparison point-cloud color length mismatch"}), 500
    float32_limit = np.finfo(np.float32).max
    if not np.isfinite(points).all() or np.any(np.abs(points) > float32_limit):
        return jsonify({"error": "Transformed Comparison coordinates cannot be represented as float32"}), 400
    if not np.isfinite(colors).all():
        return jsonify({"error": "Comparison RGB colors must be finite"}), 400
    try:
        point_data = np.ascontiguousarray(np.column_stack((points, np.clip(colors, 0.0, 1.0))), dtype=np.float32)
    except MemoryError:
        return jsonify({"error": "Comparison export is too large to fit in memory"}), 413
    if not np.isfinite(point_data).all():
        return jsonify({"error": "Comparison export contains non-finite values"}), 400
    output = io.BytesIO()
    if export_format == "ply":
        output.write(_comparison_ply_bytes(point_data[:, :3], point_data[:, 3:]))
    elif export_format == "npy":
        np.save(output, point_data, allow_pickle=False)
    else:
        if torch is None:
            return jsonify({"error": "PyTorch is required to export .pt files"}), 400
        try:
            torch.save(torch.from_numpy(point_data), output)
        except Exception as exc:
            return jsonify({"error": f"Unable to export .pt file: {exc}"}), 400
    output.seek(0)
    stem = Path(os.path.basename(source_filename)).stem or f"cloud_{cloud_id}"
    filename = f"{stem}.transformed.{export_format}"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/octet-stream")


_COMPARISON_METRIC_NAMES = {
    "accuracy": "Accuracy (Acc.)",
    "completeness": "Completeness (Comp.)",
    "chamfer": "Chamfer Distance (CD)",
    "fscore": "F-Score",
    "auc": "AUC (Area Under Curve)",
    "normal_consistency": "Normal Consistency (NC)",
}


def _comparison_transformed_xyz(source: Dict[str, Any], transform: Any) -> np.ndarray:
    """Apply the frontend Comparison transform around the source centroid."""
    xyz = np.asarray(source.get("xyz"), dtype=np.float64).reshape((-1, 3))
    return _comparison_transform_xyz_with_pivot(xyz, transform, xyz)


def _comparison_transform_xyz_with_pivot(xyz: np.ndarray, transform: Any, pivot_source: np.ndarray) -> np.ndarray:
    """Transform XYZ using a stable pivot source, which may differ from active points."""
    xyz = np.asarray(xyz, dtype=np.float64).reshape((-1, 3))
    pivot_source = np.asarray(pivot_source, dtype=np.float64).reshape((-1, 3))
    raw = transform if isinstance(transform, dict) else {}
    values = []
    for name in ("tx", "ty", "tz", "rx", "ry", "rz"):
        try:
            value = float(raw.get(name, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        if not np.isfinite(value):
            value = 0.0
        values.append(value)
    tx, ty, tz, rx, ry, rz = values
    scale = _clean_scale(raw.get("scale", 1.0))
    if not len(xyz):
        return xyz.copy()
    if len(pivot_source) == 0:
        pivot_source = xyz
    pivot = np.mean(pivot_source, axis=0)
    rotation = euler_to_rotation_matrix(rx, ry, rz)
    return ((xyz - pivot) * scale) @ rotation.T + pivot + np.asarray([tx, ty, tz], dtype=np.float64)


def _comparison_active_transformed_xyz(info: Dict[str, Any], transform: Any) -> np.ndarray:
    active_xyz, _ = _comparison_active_arrays(info)
    raw_xyz, _ = _comparison_source_arrays(info["source"])
    return _comparison_transform_xyz_with_pivot(active_xyz, transform, raw_xyz)


def _comparison_nearest(source: np.ndarray, target: np.ndarray, *, return_indices: bool = False,
                        source_block_size: int = 1024, target_block_size: int = 4096) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Find exact Euclidean nearest-neighbour distances in bounded memory."""
    source = np.asarray(source, dtype=np.float64).reshape((-1, 3))
    target = np.asarray(target, dtype=np.float64).reshape((-1, 3))
    if len(source) == 0 or len(target) == 0:
        raise ValueError("Comparison point clouds must not be empty")
    distances = np.empty(len(source), dtype=np.float64)
    indices = np.empty(len(source), dtype=np.int64) if return_indices else None
    for start in range(0, len(source), source_block_size):
        stop = min(start + source_block_size, len(source))
        block = source[start:stop]
        nearest_squared = np.full(stop - start, np.inf, dtype=np.float64)
        nearest = np.zeros(stop - start, dtype=np.int64)
        block_sq = np.sum(block * block, axis=1)[:, None]
        for target_start in range(0, len(target), target_block_size):
            target_stop = min(target_start + target_block_size, len(target))
            target_block = target[target_start:target_stop]
            squared = block_sq + np.sum(target_block * target_block, axis=1)[None, :]
            squared -= 2.0 * block @ target_block.T
            squared = np.maximum(squared, 0.0)
            local = np.argmin(squared, axis=1)
            local_squared = squared[np.arange(stop - start), local]
            improved = local_squared < nearest_squared
            nearest_squared[improved] = local_squared[improved]
            nearest[improved] = target_start + local[improved]
        distances[start:stop] = np.sqrt(nearest_squared)
        if indices is not None:
            indices[start:stop] = nearest
    return distances, indices


def _comparison_normals(points: np.ndarray, k: int = 16, source_block_size: int = 512,
                        target_block_size: int = 4096) -> Optional[np.ndarray]:
    """Estimate unoriented point normals with same-cloud k-neighbour PCA."""
    points = np.asarray(points, dtype=np.float64).reshape((-1, 3))
    if len(points) < 3:
        return None
    neighbour_count = min(int(k), len(points) - 1)
    if neighbour_count < 2:
        return None
    normals = np.zeros_like(points)
    stable = True
    for start in range(0, len(points), source_block_size):
        stop = min(start + source_block_size, len(points))
        block = points[start:stop]
        block_sq = np.sum(block * block, axis=1)[:, None]
        row_indices = np.arange(start, stop)
        best_sq = np.full((stop - start, neighbour_count), np.inf, dtype=np.float64)
        neighbours = np.zeros((stop - start, neighbour_count), dtype=np.int64)
        for target_start in range(0, len(points), target_block_size):
            target_stop = min(target_start + target_block_size, len(points))
            target_block = points[target_start:target_stop]
            squared = block_sq + np.sum(target_block * target_block, axis=1)[None, :]
            squared -= 2.0 * block @ target_block.T
            squared = np.maximum(squared, 0.0)
            local_rows = row_indices - target_start
            inside = (local_rows >= 0) & (local_rows < len(target_block))
            squared[np.flatnonzero(inside), local_rows[inside]] = np.inf
            take = min(neighbour_count, len(target_block))
            local = np.argpartition(squared, take - 1, axis=1)[:, :take]
            local_sq = np.take_along_axis(squared, local, axis=1)
            combined_sq = np.concatenate((best_sq, local_sq), axis=1)
            combined_ids = np.concatenate((neighbours, target_start + local), axis=1)
            best = np.argpartition(combined_sq, neighbour_count - 1, axis=1)[:, :neighbour_count]
            best_sq = np.take_along_axis(combined_sq, best, axis=1)
            neighbours = np.take_along_axis(combined_ids, best, axis=1)
        for row, point_index in enumerate(row_indices):
            local = points[neighbours[row]] - points[point_index]
            covariance = local.T @ local / max(1, len(local))
            try:
                eigenvalues, eigenvectors = np.linalg.eigh(covariance)
                normal = eigenvectors[:, int(np.argmin(eigenvalues))]
                stable = stable and eigenvalues[1] > max(float(eigenvalues[-1]), 1.0) * 1e-12
            except np.linalg.LinAlgError:
                normal = np.zeros(3, dtype=np.float64)
            norm = float(np.linalg.norm(normal))
            normals[point_index] = normal / norm if norm > 1e-12 else 0.0
    if not stable or not np.isfinite(normals).all() or np.any(np.linalg.norm(normals, axis=1) < 1e-12):
        return None
    return normals


def _comparison_fscore(distances_p: np.ndarray, distances_g: np.ndarray, threshold: float) -> Tuple[float, float, float]:
    precision = float(np.mean(distances_p < threshold))
    recall = float(np.mean(distances_g < threshold))
    denominator = precision + recall
    score = 2.0 * precision * recall / denominator if denominator > 0 else 0.0
    return precision, recall, score


def _comparison_markdown(filename_a: str, filename_b: str, points_a: np.ndarray, points_b: np.ndarray,
                         transforms: Dict[str, Any], tau: float, tau_max: float, auc_samples: int,
                         selected: List[str], values: Dict[str, Any], normal_note: Optional[str],
                         sor_states: Dict[str, Any]) -> str:
    def fmt(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.8f}"
        return str(value)

    lines = [
        "# Comparison Evaluation Report",
        "",
        "## Dataset",
        "",
        f"- **Prediction (Cloud A):** `{filename_a}` ({len(points_a)} points)",
        f"- **Ground Truth (Cloud B):** `{filename_b}` ({len(points_b)} points)",
        "- **Evaluation time:** " + __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "",
        "## Parameters",
        "",
        f"- `tau`: {fmt(tau)}",
        f"- `tau_max`: {fmt(tau_max)}",
        f"- AUC samples: `{auc_samples}` equally spaced thresholds",
        "- Normal estimation: same-cloud k-nearest-neighbour PCA (`k=16`)",
        "",
        "### Statistical Outlier Removal (SOR)",
        "",
        "| Cloud | Enabled | Neighbours | Effective neighbours | Stddev multiplier | Threshold | Original points | Retained points | Removed points |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cloud_id in ("a", "b"):
        sor = sor_states.get(cloud_id) if isinstance(sor_states, dict) else {}
        sor = sor if isinstance(sor, dict) else {}
        lines.append("| Cloud {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            cloud_id.upper(),
            "yes" if sor.get("enabled") else "no",
            fmt(sor.get("neighbors")),
            fmt(sor.get("effective_neighbors")),
            fmt(sor.get("stddev_multiplier")),
            fmt(sor.get("threshold")),
            fmt(sor.get("original_n_vertices")),
            fmt(sor.get("n_vertices")),
            fmt(sor.get("removed_vertices")),
        ))
    lines.extend([
        "",
        "### Applied transforms",
        "",
        "| Cloud | tx | ty | tz | rx (deg) | ry (deg) | rz (deg) | scale |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for cloud_id in ("a", "b"):
        tf = transforms.get(cloud_id) if isinstance(transforms, dict) else {}
        tf = tf if isinstance(tf, dict) else {}
        lines.append("| Cloud {} | {} | {} | {} | {} | {} | {} | {} |".format(
            cloud_id.upper(), *(fmt(tf.get(name, 0.0)) for name in ("tx", "ty", "tz", "rx", "ry", "rz")),
            fmt(tf.get("scale", 1.0))))
    lines.extend(["", "## Metrics", ""])
    definitions = {
        "accuracy": ("\u8861\u91cf\u9884\u6d4b\u51fa\u6765\u7684\u8868\u9762\u6709\u591a\u5c11\u662f\u771f\u7684\u9760\u8fd1\u771f\u503c\u8868\u9762\u3002", r"$$Accuracy=\frac{1}{|P|}\sum_{p \in P} d(p,G)$$"),
        "completeness": ("\u8861\u91cf\u771f\u503c\u8868\u9762\u6709\u6ca1\u6709\u88ab\u9884\u6d4b\u7ed3\u679c\u8986\u76d6\u5230\u3002", r"$$Completeness=\frac{1}{|G|}\sum_{g \in G}d(g,P)$$"),
        "chamfer": ("Chamfer Distance \u662f Accuracy \u548c Completeness \u7684\u7efc\u5408\u5f62\u5f0f\u3002", r"$$CD_{L1}=\frac{1}{|P|}\sum_{p \in P}d(p,G)+\frac{1}{|G|}\sum_{g \in G}d(g,P)$$"),
        "fscore": ("F-score \u662f Precision \u548c Recall \u7684\u8c03\u548c\u5e73\u5747\u6570\u3002", r"$$F-score(\tau)=\frac{2\cdot Precision(\tau)\cdot Recall(\tau)}{Precision(\tau)+Recall(\tau)}$$"),
        "auc": ("AUC \u8868\u793a F-Score-Threshold \u66f2\u7ebf\u5728\u4e0d\u540c\u5bb9\u5fcd\u8bef\u5dee\u4e0b\u7684\u6574\u4f53\u8868\u73b0\u3002", r"$$AUC=\frac{1}{\tau_{max}}\int_0^{\tau_{max}}F(\tau)d\tau$$"),
        "normal_consistency": ("NC \u8bc4\u4ef7\u9884\u6d4b\u8868\u9762\u4e0e GT \u8868\u9762\u5728\u5c40\u90e8\u671d\u5411\u4e0a\u7684\u4e00\u81f4\u7a0b\u5ea6\u3002", r"$$NC=\frac{1}{|P|}\sum_{p \in P}|n_p\cdot n_{g^*}|$$"),
    }
    for metric in selected:
        name = _COMPARISON_METRIC_NAMES[metric]
        lines.extend([f"### {name}", "", f"**Value:** `{fmt(values.get(metric))}`", "", definitions[metric][0], "", definitions[metric][1], ""])
        if metric == "fscore":
            lines.extend([f"- Precision(`tau`): `{fmt(values.get('precision'))}`", f"- Recall(`tau`): `{fmt(values.get('recall'))}`", ""])
        elif metric == "auc":
            lines.extend(["Discrete implementation uses the trapezoidal rule over the 100 sampled thresholds, then normalizes by `tau_max`.", ""])
        elif metric == "normal_consistency" and normal_note:
            lines.extend([f"**Note:** {normal_note}", ""])
    return "\n".join(lines).rstrip() + "\n"


@app.post("/api/comparison/evaluate")
def api_comparison_evaluate():
    body = request.get_json(silent=True) or {}
    selected = body.get("metrics")
    if not isinstance(selected, list):
        return jsonify({"error": "metrics must be a list"}), 400
    selected = [str(metric) for metric in selected if str(metric) in _COMPARISON_METRIC_NAMES]
    selected = list(dict.fromkeys(selected))
    if not selected:
        return jsonify({"error": "Select at least one evaluation metric"}), 400
    try:
        tau = float(body.get("tau", 0.05))
        tau_max = float(body.get("tau_max", 0.10))
    except (TypeError, ValueError):
        return jsonify({"error": "tau and tau_max must be numbers"}), 400
    if not np.isfinite(tau) or tau < 0:
        return jsonify({"error": "tau must be >= 0"}), 400
    if not np.isfinite(tau_max) or tau_max <= 0:
        return jsonify({"error": "tau_max must be > 0"}), 400
    if tau > tau_max:
        return jsonify({"error": "tau must be <= tau_max"}), 400
    auc_samples = 100
    with STATE_LOCK:
        cloud_a = COMPARISON_STATE["clouds"].get("a")
        cloud_b = COMPARISON_STATE["clouds"].get("b")
        if not cloud_a or not cloud_b:
            return jsonify({"error": "Load both comparison point clouds before evaluating"}), 400
        transforms = body.get("transforms") if isinstance(body.get("transforms"), dict) else {}
        try:
            points_a = _comparison_active_transformed_xyz(cloud_a, transforms.get("a"))
            points_b = _comparison_active_transformed_xyz(cloud_b, transforms.get("b"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        filename_a, filename_b = cloud_a["filename"], cloud_b["filename"]
        sor_states = {
            cloud_id: _comparison_sor_metadata(cloud_id, info)["sor"]
            for cloud_id, info in (("a", cloud_a), ("b", cloud_b))
        }
    try:
        distances_p, nearest_gt = _comparison_nearest(points_a, points_b, return_indices=True)
        distances_g, _ = _comparison_nearest(points_b, points_a)
        values: Dict[str, Any] = {}
        accuracy = float(np.mean(distances_p))
        completeness = float(np.mean(distances_g))
        if "accuracy" in selected:
            values["accuracy"] = accuracy
        if "completeness" in selected:
            values["completeness"] = completeness
        if "chamfer" in selected:
            values["chamfer"] = accuracy + completeness
        precision, recall, fscore = _comparison_fscore(distances_p, distances_g, tau)
        if "fscore" in selected:
            values.update({"precision": precision, "recall": recall, "fscore": fscore})
        if "auc" in selected:
            thresholds = np.linspace(0.0, tau_max, auc_samples)
            scores = np.asarray([_comparison_fscore(distances_p, distances_g, threshold)[2] for threshold in thresholds])
            integrate = getattr(np, "trapezoid", None) or np.trapz
            values["auc"] = float(integrate(scores, thresholds) / tau_max)
        normal_note = None
        if "normal_consistency" in selected:
            normals_p = _comparison_normals(points_a, k=16)
            normals_g = _comparison_normals(points_b, k=16)
            if normals_p is None or normals_g is None:
                values["normal_consistency"] = None
                normal_note = "NC requires non-degenerate local PCA neighbourhoods in both clouds."
            else:
                dots = np.abs(np.sum(normals_p * normals_g[nearest_gt], axis=1))
                values["normal_consistency"] = float(np.mean(np.clip(dots, 0.0, 1.0)))
        markdown = _comparison_markdown(filename_a, filename_b, points_a, points_b, transforms, tau, tau_max,
                                        auc_samples, selected, values, normal_note, sor_states)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"comparison_evaluation_{timestamp}.md"
    path = os.path.join(EVALUATION_ROOT, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)
    return jsonify({"ok": True, "filename": filename, "download_url": f"/api/comparison/evaluations/{filename}",
                    "selected_metrics": selected, "values": values, "markdown": markdown})


@app.get("/api/comparison/evaluations/<filename>")
def api_comparison_evaluation_download(filename: str):
    if os.path.basename(filename) != filename or not filename.startswith("comparison_evaluation_") or not filename.endswith(".md"):
        return jsonify({"error": "Invalid evaluation filename"}), 400
    path = os.path.join(EVALUATION_ROOT, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "Evaluation report not found"}), 404
    return send_file(path, as_attachment=True, download_name=filename, mimetype="text/markdown")


@app.get("/api/parts")
def api_parts():
    with STATE_LOCK:
        return jsonify({"parts": [_serialize_part(pid, part) for pid, part in STATE["parts"].items()]})


@app.post("/api/parts")
def api_create_part_v2():
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        if not STATE["loaded"] or STATE["xyz"] is None:
            return jsonify({"error": "Upload a point cloud before creating a Part"}), 400
        try:
            indices = _valid_static_indices(body.get("vertex_indices", []))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        pid = STATE["next_part_id"]
        STATE["next_part_id"] += 1
        _remove_static_indices_from_parts(indices)
        pivot = np.mean(STATE["xyz"][indices], axis=0).tolist() if indices else [0, 0, 0]
        STATE["parts"][pid] = {"name": str(body.get("name") or f"Part {pid}"), "color": _color_for(pid),
                                "pivot": pivot, "vertex_indices": set(indices)}
        STATE["part_id_array"][indices] = pid
        STATE["tracks"][pid] = []
        return jsonify({"ok": True, "part": _serialize_part(pid, STATE["parts"][pid])}), 201


@app.put("/api/parts/<int:pid>")
def api_update_part_v2(pid):
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        part = STATE["parts"].get(pid)
        if part is None:
            return jsonify({"error": "Part not found"}), 404
        try:
            if "name" in body:
                part["name"] = str(body["name"])
            for field in ("pivot", "color"):
                if field in body:
                    values = body[field]
                    if not isinstance(values, list) or len(values) != 3:
                        raise ValueError(f"{field} must contain exactly three values")
                    parsed = [float(value) for value in values]
                    if not all(math.isfinite(value) for value in parsed):
                        raise ValueError(f"{field} values must be finite")
                    if field == "color" and not all(0.0 <= value <= 1.0 for value in parsed):
                        raise ValueError("color values must be in the range [0, 1]")
                    part[field] = parsed
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "part": _serialize_part(pid, part)})


@app.delete("/api/parts/<int:pid>")
def api_delete_part_v2(pid):
    """Remove a Part and its animation, leaving its static vertices unassigned."""
    with STATE_LOCK:
        part = STATE["parts"].get(pid)
        if part is None:
            return jsonify({"error": "Part not found"}), 404
        if part.get("is_4dgs", False):
            STATE["4dgs_parts"].pop(pid, None)
        else:
            indices = sorted(part.get("vertex_indices", set()))
            if indices and STATE["part_id_array"] is not None:
                STATE["part_id_array"][indices] = -1
        STATE["parts"].pop(pid, None)
        STATE["tracks"].pop(pid, None)
        STATE["loaded"] = _workspace_has_data()
        return jsonify({"ok": True, "deleted_part_id": pid})


@app.delete("/api/parts/<int:pid>/vertices")
def api_delete_part_vertices(pid):
    """Destructively delete a static Part and all of its source vertices."""
    with STATE_LOCK:
        part = STATE["parts"].get(pid)
        if part is None:
            return jsonify({"error": "Part not found"}), 404
        if part.get("is_4dgs", False):
            return jsonify({"error": "Vertex deletion is only supported for static Parts"}), 400
        deleted = _delete_static_vertices(sorted(part.get("vertex_indices", set())))
        STATE["parts"].pop(pid, None)
        STATE["tracks"].pop(pid, None)
        STATE["loaded"] = _workspace_has_data()
        return jsonify({"ok": True, "deleted_part_id": pid, "deleted_vertices": deleted,
                        "n_vertices": int(STATE["n_vertices"])})


@app.post("/api/parts/<int:pid>/assign")
def api_assign_part_v2(pid):
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        part = STATE["parts"].get(pid)
        if part is None:
            return jsonify({"error": "Part not found"}), 404
        if part.get("is_4dgs", False):
            return jsonify({"error": "Static vertices cannot be assigned to a 4DGS Part"}), 400
        try:
            indices = _valid_static_indices(body.get("vertex_indices", []))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        _remove_static_indices_from_parts(indices)
        part["vertex_indices"].update(indices)
        STATE["part_id_array"][indices] = pid
        try:
            _refresh_static_part_pivot(pid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "part": _serialize_part(pid, part)})


@app.get("/api/parts/<int:pid>/centroid")
def api_part_centroid_v2(pid):
    with STATE_LOCK:
        part = STATE["parts"].get(pid)
        if part is None:
            return jsonify({"error": "Part not found"}), 404
        if part.get("is_4dgs", False):
            return jsonify({"error": "A 4DGS Part has no static vertices for centroid calculation"}), 400
        try:
            pivot = _refresh_static_part_pivot(pid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "pivot": pivot, "part": _serialize_part(pid, part)})


def _clean_keyframe(body: Dict[str, Any], frame_default: int = 0) -> Dict[str, Any]:
    """Validate and normalize the public keyframe representation."""
    frame = int(body.get("frame", frame_default))
    frame = max(0, min(frame, max(0, int(STATE["num_frames"]) - 1)))
    values = {name: float(body.get(name, 0.0)) for name in ("tx", "ty", "tz", "rx", "ry", "rz")}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("transform values must be finite")
    return {"frame": frame, **values}


@app.get("/api/keyframes/<int:pid>")
def api_get_keyframes(pid):
    with STATE_LOCK:
        if pid not in STATE["parts"]:
            return jsonify({"error": "Part not found"}), 404
        return jsonify({"pid": pid, "keyframes": sorted(STATE["tracks"].get(pid, []), key=lambda key: key["frame"])})


@app.post("/api/keyframes/<int:pid>")
def api_put_keyframe(pid):
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        if pid not in STATE["parts"]:
            return jsonify({"error": "Part not found"}), 404
        try:
            key = _clean_keyframe(body)
        except (TypeError, ValueError, OverflowError) as exc:
            return jsonify({"error": f"Invalid keyframe: {exc}"}), 400
        keys = [item for item in STATE["tracks"].get(pid, []) if int(item.get("frame", -1)) != key["frame"]]
        keys.append(key)
        STATE["tracks"][pid] = sorted(keys, key=lambda item: item["frame"])
        return jsonify({"ok": True, "pid": pid, "keyframes": STATE["tracks"][pid]})


@app.delete("/api/keyframes/<int:pid>/<int:frame>")
def api_delete_keyframe(pid, frame):
    with STATE_LOCK:
        if pid not in STATE["parts"]:
            return jsonify({"error": "Part not found"}), 404
        keys = STATE["tracks"].get(pid, [])
        if not any(int(item.get("frame", -1)) == frame for item in keys):
            return jsonify({"error": "Keyframe not found"}), 404
        STATE["tracks"][pid] = [item for item in keys if int(item.get("frame", -1)) != frame]
        return jsonify({"ok": True, "pid": pid, "keyframes": STATE["tracks"][pid]})


@app.get("/api/settings")
def api_get_settings():
    with STATE_LOCK:
        return jsonify({"num_frames": int(STATE["num_frames"]), "interpolation_method": STATE["interpolation_method"]})


def _update_settings(body: Dict[str, Any]):
    try:
        num_frames = int(body.get("num_frames", STATE["num_frames"]))
    except (TypeError, ValueError):
        return "num_frames must be an integer"
    if num_frames < 1:
        return "num_frames must be at least 1"
    if num_frames > 10000:
        return "num_frames must be at most 10000"
    method = body.get("interpolation_method", STATE["interpolation_method"])
    if method not in ("linear", "catmull_rom", "catmull-rom"):
        return "interpolation_method must be linear or catmull_rom"
    STATE["num_frames"] = num_frames
    STATE["interpolation_method"] = "catmull_rom" if method in ("catmull_rom", "catmull-rom") else "linear"
    return None


@app.put("/api/settings")
def api_put_settings():
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        error = _update_settings(body)
        if error:
            return jsonify({"error": error}), 400
        return jsonify({"ok": True, "num_frames": STATE["num_frames"], "interpolation_method": STATE["interpolation_method"]})


@app.get("/api/frame_transforms/<int:frame>")
def api_frame_transforms(frame):
    with STATE_LOCK:
        if not _workspace_has_data():
            return jsonify({"error": "No point-cloud data is loaded"}), 400
        clamped = max(0, min(int(frame), max(0, STATE["num_frames"] - 1)))
        payload = {str(pid): {name: float(_key_for(pid, clamped).get(name, 0.0))
                              for name in ("tx", "ty", "tz", "rx", "ry", "rz")}
                    for pid in STATE["parts"]}
    return jsonify(payload)


def _clean_color_mode(value: Any = "original") -> str:
    mode = str(value or "original").strip().lower()
    if mode not in ("original", "edited"):
        raise ValueError("color_mode must be either 'original' or 'edited'")
    return mode


def _export_frame_payload(frame: int, scale: float = 1.0, color_mode: str = "original") -> Dict[str, Any]:
    """Build one exportable frame, including 4DGS attributes when present."""
    payload = compute_full_frame_data(frame, apply_transforms=True)
    payload["xyz"] = _scale_xyz_about_centroid(payload["xyz"], scale)
    payload["colors"] = payload["original_colors"] if color_mode == "original" else payload["colors"]
    return payload


@app.post("/api/export")
def api_export():
    body = request.get_json(silent=True) or {}
    output_dir = body.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir.strip():
        return jsonify({"error": "output_dir is required"}), 400
    try:
        scale = _clean_scale(body.get("scale", 1.0))
        color_mode = _clean_color_mode(body.get("color_mode", "original"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with STATE_LOCK:
        if not STATE["loaded"] or not _workspace_has_data():
            return jsonify({"error": "No point-cloud data is loaded"}), 400
        if STATE.get("export_active", False):
            return jsonify({"error": "An export is already in progress"}), 409
        frame_count = int(STATE["num_frames"])
        single_file = frame_count == 1
        output_path = output_dir if output_dir.lower().endswith(".pt") else output_dir + ".pt"
        output_target = _resolve_user_path(output_path if single_file else output_dir)
        try:
            os.makedirs(os.path.dirname(output_target) if single_file else output_target, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": str(exc)}), 400
        STATE["export_active"] = True
        STATE["export_done"] = False
        STATE["export_progress"] = 0
        STATE["export_dir"] = output_target

    def worker():
        try:
            for index in range(frame_count):
                payload = _export_frame_payload(index, scale=scale, color_mode=color_mode)
                path = output_target if single_file else os.path.join(output_target, f"frame_{index:04d}.pt")
                _write_pt(path, payload)
                with STATE_LOCK:
                    STATE["export_progress"] = int((index + 1) * 100 / max(1, frame_count))
        except Exception:
            with STATE_LOCK:
                STATE["export_progress"] = -1
        finally:
            with STATE_LOCK:
                STATE["export_active"] = False
                STATE["export_done"] = STATE["export_progress"] == 100

    threading.Thread(target=worker, daemon=True, name="4dgs-export").start()
    result = {"ok": True, "num_frames": frame_count, "output_dir": output_target, "color_mode": color_mode}
    if single_file:
        result["output_path"] = output_target
    return jsonify(result)


@app.get("/api/export/status")
def api_export_status():
    with STATE_LOCK:
        return jsonify({"progress": int(STATE.get("export_progress", -1)),
                        "done": bool(STATE.get("export_done", False)),
                        "output_dir": STATE.get("export_dir")})


@app.post("/api/export_current")
def api_export_current_v2():
    body = request.get_json(silent=True) or {}
    output_path = body.get("output_path")
    if not isinstance(output_path, str) or not output_path.strip():
        return jsonify({"error": "output_path is required"}), 400
    output_path = output_path.strip()
    try:
        frame = int(body.get("frame", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "frame must be an integer"}), 400
    try:
        scale = _clean_scale(body.get("scale", 1.0))
        color_mode = _clean_color_mode(body.get("color_mode", "original"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with STATE_LOCK:
        if not STATE["loaded"] or not _workspace_has_data():
            return jsonify({"error": "No point-cloud data is loaded"}), 400
        frame = max(0, min(frame, max(0, STATE["num_frames"] - 1)))
        output_path = output_path if output_path.lower().endswith(".pt") else output_path + ".pt"
        output_path = _resolve_user_path(output_path)
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            payload = _export_frame_payload(frame, scale=scale, color_mode=color_mode)
            _write_pt(output_path, payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "output_path": output_path, "n_vertices": int(payload["n_vertices"]), "frame": frame, "color_mode": color_mode})


@app.post("/api/create-part")
def api_create_part():
    body = request.get_json(force=True); indices = sorted(set(int(i) for i in body.get("indices", [])))
    with STATE_LOCK:
        if not STATE["loaded"]: return jsonify({"error": "请先上传点云"}), 400
        indices = [i for i in indices if 0 <= i < STATE["n_vertices"]]
        pid = STATE["next_part_id"]; STATE["next_part_id"] += 1; pivot = np.mean(STATE["xyz"][indices], axis=0).tolist() if indices else [0,0,0]
        # A static point has exactly one owner, otherwise splitting a Part
        # would render and export the same point more than once.
        for existing in STATE["parts"].values():
            if not existing.get("is_4dgs"):
                existing.get("vertex_indices", set()).difference_update(indices)
        STATE["parts"][pid] = {"name": body.get("name") or f"Part {pid}", "color": _color_for(pid), "pivot": pivot, "vertex_indices": set(indices)}
        if STATE["part_id_array"] is not None: STATE["part_id_array"][indices] = pid
    return jsonify(state_summary())

@app.post("/api/part/<int:pid>")
def api_part(pid):
    body = request.get_json(force=True)
    with STATE_LOCK:
        if pid not in STATE["parts"]: return jsonify({"error": "part not found"}), 404
        part = STATE["parts"][pid]
        if "name" in body: part["name"] = str(body["name"])
        if "pivot" in body: part["pivot"] = [float(x) for x in body["pivot"][:3]]
        if "color" in body: part["color"] = [float(x) for x in body["color"][:3]]
    return jsonify(state_summary())

@app.post("/api/keyframes")
def api_keyframes():
    body = request.get_json(force=True); pid = int(body.get("pid", -1)); keys = body.get("keyframes", [])
    with STATE_LOCK:
        if pid not in STATE["parts"]: return jsonify({"error": "part not found"}), 404
        clean = []
        for k in keys:
            clean.append({"frame": max(0, min(int(k.get("frame", 0)), STATE["num_frames"]-1)), **{n: float(k.get(n, 0)) for n in ("tx", "ty", "tz", "rx", "ry", "rz")}})
        STATE["tracks"][pid] = sorted(clean, key=lambda x: x["frame"])
    return jsonify(state_summary())

@app.post("/api/settings")
def api_settings():
    body = request.get_json(silent=True) or {}
    with STATE_LOCK:
        error = _update_settings(body)
        if error:
            return jsonify({"error": error}), 400
    return jsonify(state_summary())

@app.post("/api/import-4dgs")
def api_import_4dgs():
    files = request.files.getlist("files"); names = request.form.getlist("filenames") or [f.filename for f in files]
    if not files: return jsonify({"error": "请选择 .pt/.npy 帧序列"}), 400
    frames = []
    try:
        for f in files:
            extension = os.path.splitext(f.filename)[1].lower()
            if extension not in (".pt", ".npy"): continue
            frames.append(_load_pointcloud_bytes(f.read(), extension))
    except Exception as exc: return jsonify({"error": str(exc)}), 400
    if not frames: return jsonify({"error": "没有有效的 .pt/.npy 文件"}), 400
    with STATE_LOCK:
        pid = STATE["next_part_id"]; STATE["next_part_id"] += 1; base = frames[0]
        max_degree = max(int(frame.get("sh_degree", 0)) for frame in frames)
        target_k = max(0, (max_degree + 1) ** 2 - 1)
        for frame_data_item in frames:
            frame_data_item["sh_rest"] = _pad_sh_rest(frame_data_item.get("sh_rest"), frame_data_item["n_vertices"], target_k)
            frame_data_item["sh_degree"] = max_degree
        STATE["parts"][pid] = {"name": request.form.get("name") or f"4DGS Part {pid}", "color": _color_for(pid), "pivot": np.mean(base["xyz"], axis=0).tolist() if base["n_vertices"] else [0,0,0], "vertex_indices": set(), "is_4dgs": True}
        STATE["4dgs_parts"][pid] = {"frames": frames, "n_frames_src": len(frames), "sh_degree": max_degree, "loop": True, "filenames": names}
        STATE["tracks"][pid] = []
    return jsonify(state_summary())

@app.post("/api/export/current")
def api_export_current():
    if torch is None: return jsonify({"error": "PyTorch 未安装，无法导出"}), 400
    frame = int((request.get_json(silent=True) or {}).get("frame", 0)); payload = frame_payload(frame)
    path = os.path.join(EXPORT_ROOT, f"frame_{frame:04d}.pt")
    _write_pt(path, frame_data(frame)); return jsonify({"path": path, "filename": os.path.basename(path), "download": f"/api/download/current/{frame}"})

@app.post("/api/export/all")
def api_export_all():
    if torch is None: return jsonify({"error": "PyTorch 未安装，无法导出"}), 400
    def worker():
        with STATE_LOCK: STATE["export_progress"] = 0; count = STATE["num_frames"]
        out = tempfile.mkdtemp(prefix="4dgs_export_", dir=EXPORT_ROOT)
        for i in range(count):
            _write_pt(os.path.join(out, f"frame_{i:04d}.pt"), frame_data(i))
            with STATE_LOCK: STATE["export_progress"] = int((i+1)*100/count)
        with STATE_LOCK: STATE["export_dir"] = out
    threading.Thread(target=worker, daemon=True).start(); return jsonify({"started": True})

@app.get("/api/export/progress")
def api_export_progress():
    with STATE_LOCK: return jsonify({"progress": STATE["export_progress"], "dir": STATE["export_dir"]})


@app.get("/api/download/current/<int:frame>")
def api_download_current(frame):
    path = os.path.join(EXPORT_ROOT, f"frame_{frame:04d}.pt")
    if not os.path.isfile(path): return jsonify({"error": "文件尚未导出"}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.get("/api/download/all")
def api_download_all():
    with STATE_LOCK: export_dir = STATE["export_dir"]
    if not export_dir or not os.path.isdir(export_dir): return jsonify({"error": "尚未完成全部帧导出"}), 404
    zip_path = os.path.join(EXPORT_ROOT, "4dgs_animation_frames.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(os.listdir(export_dir)):
            if name.endswith(".pt"): archive.write(os.path.join(export_dir, name), name)
    return send_file(zip_path, as_attachment=True, download_name="4dgs_animation_frames.zip")


HTML_PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Part-Level 4DGS Animation Editor</title>
<style>
:root{--bg:#0b1020;--panel:#121a2b;--panel2:#18233a;--line:#273650;--text:#e7edf7;--muted:#8fa1bf;--accent:#43b7ff;--good:#48d597;--danger:#ff6b6b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}button,input,select{font:inherit;color:inherit}button{border:1px solid var(--line);background:#1c2a43;padding:8px 11px;border-radius:5px;cursor:pointer}button:hover{border-color:var(--accent);background:#233856}.app{height:100vh;display:grid;grid-template-columns:280px 1fr 320px;grid-template-rows:58px 1fr 190px}.top{grid-column:1/-1;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px;padding:0 18px;background:#0f1729}.brand{font-weight:700;letter-spacing:.3px;font-size:16px}.status{color:var(--muted);font-size:12px}.toolbar{margin-left:auto;display:flex;gap:8px}.side{background:var(--panel);padding:14px;border-right:1px solid var(--line);overflow:auto}.right{background:var(--panel);padding:14px;border-left:1px solid var(--line);overflow:auto}.section{border-bottom:1px solid var(--line);padding-bottom:15px;margin-bottom:15px}.section h3{margin:0 0 10px;font-size:13px;color:#c3d1e8}.row{display:flex;gap:7px;align-items:center;margin:7px 0}.row>*{min-width:0}.grow{flex:1}.small{font-size:12px;color:var(--muted)}input[type=text],input[type=number],select{width:100%;background:#0c1425;border:1px solid var(--line);border-radius:4px;padding:7px}.file{width:100%;border:1px dashed #385071;padding:10px;border-radius:5px}.part{display:flex;align-items:center;gap:8px;padding:8px;border:1px solid transparent;border-radius:5px;cursor:pointer}.part:hover,.part.active{background:var(--panel2);border-color:var(--line)}.swatch{width:11px;height:11px;border-radius:50%}.viewport{position:relative;min-width:0;background:#080d18}.viewport canvas{display:block;width:100%;height:100%}.hint{position:absolute;left:14px;top:12px;color:var(--muted);font-size:12px;pointer-events:none}.selection{position:absolute;border:1px dashed var(--accent);background:rgba(67,183,255,.12);pointer-events:none;display:none}.timeline{grid-column:1/-1;border-top:1px solid var(--line);background:#0f1729;padding:12px 18px;display:flex;flex-direction:column;gap:10px}.timeline-head{display:flex;align-items:center;gap:10px}.timeline-head input{width:80px}.track{height:36px;position:relative;background:#0b1220;border:1px solid var(--line);border-radius:4px}.ticks{display:flex;justify-content:space-between;color:var(--muted);font-size:10px;padding:3px 5px}.key{position:absolute;top:17px;width:9px;height:9px;background:var(--accent);transform:translateX(-50%) rotate(45deg)}.playhead{position:absolute;top:0;bottom:0;width:2px;background:var(--danger);transform:translateX(-50%)}.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.kv label{font-size:11px;color:var(--muted)}.kv input{margin-top:2px}.log{font-size:12px;color:var(--muted);white-space:pre-wrap;max-height:80px;overflow:auto}
@media(max-width:1000px){.app{grid-template-columns:220px 1fr;grid-template-rows:58px 1fr 190px}.right{display:none}}
<aside class="side"><div class="section"><h3>Data</h3><input id="fileInput" class="file" type="file" multiple accept=".ply,.pt,.npy"><input id="appendInput" class="file" type="file" multiple accept=".ply,.pt,.npy" style="display:none"><input id="frameInput" class="file" type="file" multiple accept=".pt,.npy" webkitdirectory directory style="display:none"><div id="progress" class="small"></div></div><div class="section"><h3>Parts</h3><div id="parts"></div><div class="row"><button id="newPart" class="grow">Create Part</button><button id="deletePart">Delete</button></div></div><div class="section"><h3>Viewport</h3><div class="row"><label class="grow">Point size <input id="pointSize" type="range" min="1" max="12" step=".5" value="3"></label></div><div class="row"><button id="resetView" class="grow">Reset View</button><button id="clearSelection">Clear</button></div></div><div class="section"><h3>Log</h3><div id="log" class="log"></div></div></aside>
<main id="viewport" class="viewport"><div class="hint">拖拽矩形框选点 · 左键旋转 · 右键平移 · 滚轮缩放</div><div id="selection" class="selection"></div></main>
<aside class="right"><div class="section"><h3>Part 属性</h3><div class="row"><label class="grow small">名称<input id="partName" type="text"></label></div><div class="small">Pivot</div><div class="kv"><label>X<input id="px" type="number" step=".01"></label><label>Y<input id="py" type="number" step=".01"></label><label>Z<input id="pz" type="number" step=".01"></label></div><button id="savePart" style="margin-top:8px;width:100%">保存属性</button></div><div class="section"><h3>关键帧</h3><div class="row"><label class="grow small">帧<input id="kfFrame" type="number" min="0" value="0"></label><button id="addKey">添加/更新关键帧</button></div><div class="small">平移</div><div class="kv"><label>X<input id="tx" type="number" step=".01" value="0"></label><label>Y<input id="ty" type="number" step=".01" value="0"></label><label>Z<input id="tz" type="number" step=".01" value="0"></label></div><div class="small" style="margin-top:8px">旋转 (弧度)</div><div class="kv"><label>X<input id="rx" type="number" step=".01" value="0"></label><label>Y<input id="ry" type="number" step=".01" value="0"></label><label>Z<input id="rz" type="number" step=".01" value="0"></label></div><div id="keyList" class="small" style="margin-top:8px"></div></div><div class="section"><h3>动画设置</h3><div class="row"><label class="grow small">总帧数<input id="numFrames" type="number" min="1" max="10000" value="1"></label><label class="grow small">插值<select id="interp"><option value="linear">Linear</option><option value="catmull-rom">Catmull-Rom</option></select></label></div><button id="saveSettings" style="width:100%">应用设置</button></div></aside>
<section class="timeline"><div class="timeline-head"><button id="play">播放</button><button id="stop">停止</button><span>当前帧</span><input id="currentFrame" type="number" min="0" max="0" value="0"><input id="scrub" class="grow" type="range" min="0" max="0" value="0"><span id="frameLabel" class="small">0 / 0</span></div><div id="track" class="track"><div class="ticks"><span>0</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div><div id="playhead" class="playhead" style="left:0%"></div></div></section></div>
<script src="/static/three.min.js"></script><script src="/static/OrbitControls.js"></script><script>
const $=id=>document.getElementById(id); let state={parts:[],tracks:{},num_frames:1}; let selectedPid=null, selectedIndices=[], visibleSourceIndices=[], points, scene, camera, renderer, controls, animTimer=null, drag=null;
function log(s){$('log').textContent=new Date().toLocaleTimeString()+' '+s+'\n'+$('log').textContent}
async function api(url,opts={}){const r=await fetch(url,opts); const d=await r.json(); if(!r.ok) throw Error(d.error||r.statusText); return d}
async function refresh(){state=await api('/api/state'); $('status').textContent=state.loaded?`${state.filename} · ${state.n_vertices} 点`:'未加载点云'; $('numFrames').value=state.num_frames; $('interp').value=state.interpolation_method; $('scrub').max=Math.max(0,state.num_frames-1); renderParts(); renderTrack(); loadFrame(+$('currentFrame').value||0)}
function renderParts(){ $('parts').innerHTML=''; state.parts.forEach(p=>{const d=document.createElement('div');d.className='part '+(p.id===selectedPid?'active':'');d.onclick=()=>selectPart(p.id);d.innerHTML=`<span class="swatch" style="background:rgb(${p.color.map(x=>x*255).join(',')})"></span><span class="grow">${p.name}</span><span class="small">${p.count}</span>`;$('parts').appendChild(d)}) }
function selectPart(pid){selectedPid=pid;const p=state.parts.find(x=>x.id===pid);if(!p)return;$('partName').value=p.name;['x','y','z'].forEach((a,i)=>$('p'+a).value=p.pivot[i]);renderParts();renderKeyList()}
function renderKeyList(){const ks=state.tracks[String(selectedPid)]||[];$('keyList').innerHTML=ks.length?ks.map(k=>`帧 ${k.frame}: T(${k.tx.toFixed(2)}, ${k.ty.toFixed(2)}, ${k.tz.toFixed(2)}) R(${k.rx.toFixed(2)}, ${k.ry.toFixed(2)}, ${k.rz.toFixed(2)})`).join('<br>'):'暂无关键帧'}
function renderTrack(){const t=$('track');t.querySelectorAll('.key').forEach(x=>x.remove());if(selectedPid===null)return;(state.tracks[String(selectedPid)]||[]).forEach(k=>{const e=document.createElement('div');e.className='key';e.style.left=(k.frame/Math.max(1,state.num_frames-1)*100)+'%';t.appendChild(e)})}
function createInfiniteGrid(){const geometry=new THREE.PlaneBufferGeometry(10000,10000);const material=new THREE.ShaderMaterial({uniforms:{gridColor:{value:new THREE.Color(0x1b2940)}},vertexShader:'varying vec3 vWorldPosition;void main(){vec4 worldPosition=modelMatrix*vec4(position,1.0);vWorldPosition=worldPosition.xyz;gl_Position=projectionMatrix*viewMatrix*worldPosition;}',fragmentShader:'varying vec3 vWorldPosition;uniform vec3 gridColor;float gridLine(float coordinate,float spacing,float width){float scaled=coordinate/spacing;float distanceToLine=abs(fract(scaled-0.5)-0.5);float aa=fwidth(scaled);return 1.0-smoothstep(width+aa,width+aa*2.0,distanceToLine);}void main(){float intensity=max(gridLine(vWorldPosition.x,1.0,.018),gridLine(vWorldPosition.y,1.0,.018));if(intensity<.01)discard;gl_FragColor=vec4(gridColor,intensity*.78);}',extensions:{derivatives:true},side:THREE.DoubleSide,transparent:true,depthTest:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1});const grid=new THREE.Mesh(geometry,material);grid.renderOrder=-10;grid.userData.infiniteGrid=true;return grid}
function syncInfiniteGrid(targetScene,target){const grid=targetScene&&targetScene.userData.infiniteGrid;if(!grid||!target)return;const snap=1000;grid.position.set(Math.round(target.x/snap)*snap,Math.round(target.y/snap)*snap,0)}
function init3d(){scene=new THREE.Scene();scene.background=new THREE.Color(0x080d18);camera=new THREE.PerspectiveCamera(55,1,.01,10000);camera.up.set(0,0,1);camera.position.set(3,-4,2.5);renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(devicePixelRatio);$('viewport').appendChild(renderer.domElement);controls=new THREE.OrbitControls(camera,renderer.domElement);controls.target.set(0,0,0);const grid=createInfiniteGrid();scene.add(grid);scene.userData.infiniteGrid=grid;window.addEventListener('resize',resize);resize();renderer.setAnimationLoop(()=>{syncInfiniteGrid(scene,controls.target);renderer.render(scene,camera)});renderer.domElement.addEventListener('pointerdown',startDrag);renderer.domElement.addEventListener('pointermove',moveDrag);renderer.domElement.addEventListener('pointerup',endDrag)}
function resize(){const r=$('viewport').getBoundingClientRect();camera.aspect=r.width/r.height;camera.updateProjectionMatrix();renderer.setSize(r.width,r.height)}
function startDrag(e){if(e.button!==0)return;drag={x:e.offsetX,y:e.offsetY};$('selection').style.display='block';$('selection').style.left=e.offsetX+'px';$('selection').style.top=e.offsetY+'px';$('selection').style.width='0';$('selection').style.height='0'}
function moveDrag(e){if(!drag)return;const x=Math.min(drag.x,e.offsetX),y=Math.min(drag.y,e.offsetY),w=Math.abs(e.offsetX-drag.x),h=Math.abs(e.offsetY-drag.y);Object.assign($('selection').style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'})}
function endDrag(e){if(!drag)return;const box=$('selection').getBoundingClientRect(), rect=renderer.domElement.getBoundingClientRect();selectedIndices=[];if(points){const pos=points.geometry.attributes.position;for(let i=0;i<pos.count;i++){const v=new THREE.Vector3().fromBufferAttribute(pos,i).project(camera);const sx=rect.left+(v.x+1)*rect.width/2,sy=rect.top+(-v.y+1)*rect.height/2;if(sx>=box.left&&sx<=box.right&&sy>=box.top&&sy<=box.bottom&&visibleSourceIndices[i]>=0)selectedIndices.push(visibleSourceIndices[i])}}selectedIndices=[...new Set(selectedIndices)];log(`选中 ${selectedIndices.length} 个静态点`);drag=null}
async function loadFrame(f){if(!state.loaded&&!state.parts.length)return;try{const d=await api('/api/frame/'+f);visibleSourceIndices=d.source_indices||[];if(points)scene.remove(points);const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(d.xyz.flat(),3));geo.setAttribute('color',new THREE.Float32BufferAttribute(d.colors.flat(),3));const mat=new THREE.PointsMaterial({size:+$('pointSize').value,vertexColors:true,sizeAttenuation:true});points=new THREE.Points(geo,mat);scene.add(points);if(d.xyz.length&&!camera.userData.fitted){const b=new THREE.Box3().setFromObject(points),c=b.getCenter(new THREE.Vector3()),s=b.getSize(new THREE.Vector3()).length();controls.target.copy(c);camera.position.copy(c).add(new THREE.Vector3(s,-s,s*.7));camera.userData.fitted=true}}catch(e){log(e.message)}}
async function upload(){const fs=$('fileInput').files;if(!fs.length)return;const fd=new FormData();[...fs].forEach(f=>fd.append('files',f));$('progress').textContent='上传中…';try{await api('/api/upload',{method:'POST',body:fd});log('点云加载完成');await refresh()}catch(e){log(e.message)}$('progress').textContent=''}
async function import4d(){const fs=$('frameInput').files;if(!fs.length)return;const fd=new FormData();[...fs].sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true})).forEach(f=>{fd.append('files',f);fd.append('filenames',f.name)});try{await api('/api/import-4dgs',{method:'POST',body:fd});log('4DGS 帧序列导入完成');await refresh()}catch(e){log(e.message)}}
$('uploadBtn').onclick=()=>$('fileInput').click();$('fileInput').onchange=upload;$('importBtn').onclick=()=>$('frameInput').click();$('frameInput').onchange=import4d;$('pointSize').oninput=()=>{if(points)points.material.size=+$('pointSize').value};$('resetView').onclick=()=>{camera.userData.fitted=false;camera.position.set(3,-4,2.5);controls.target.set(0,0,0)};$('clearSelection').onclick=()=>{selectedIndices=[];$('selection').style.display='none'};
$('newPart').onclick=async()=>{if(!selectedIndices.length)return log('请先框选点');try{await api('/api/create-part',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({indices:selectedIndices})});selectedIndices=[];log('已创建新 Part');await refresh()}catch(e){log(e.message)}};
$('savePart').onclick=async()=>{if(selectedPid===null)return;try{await api('/api/part/'+selectedPid,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('partName').value,pivot:[+$('px').value,+$('py').value,+$('pz').value]})});await refresh();selectPart(selectedPid)}catch(e){log(e.message)}};
$('addKey').onclick=async()=>{if(selectedPid===null)return;const ks=[...(state.tracks[String(selectedPid)]||[])];const k={frame:+$('kfFrame').value,tx:+$('tx').value,ty:+$('ty').value,tz:+$('tz').value,rx:+$('rx').value,ry:+$('ry').value,rz:+$('rz').value};const i=ks.findIndex(x=>x.frame===k.frame);if(i>=0)ks[i]=k;else ks.push(k);try{await api('/api/keyframes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pid:selectedPid,keyframes:ks})});await refresh();selectPart(selectedPid)}catch(e){log(e.message)}};
$('saveSettings').onclick=async()=>{try{await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({num_frames:+$('numFrames').value,interpolation_method:$('interp').value})});await refresh()}catch(e){log(e.message)}};
$('scrub').oninput=()=>{$('currentFrame').value=$('scrub').value;$('frameLabel').textContent=`${$('scrub').value} / ${state.num_frames-1}`;movePlayhead();loadFrame(+$('scrub').value)};$('currentFrame').onchange=()=>{$('scrub').value=$('currentFrame').value;$('scrub').oninput()};function movePlayhead(){$('playhead').style.left=(+$('currentFrame').value/Math.max(1,state.num_frames-1)*100)+'%'};$('play').onclick=()=>{if(animTimer)return;animTimer=setInterval(()=>{let f=(+$('currentFrame').value+1)%state.num_frames;$('currentFrame').value=f;$('scrub').value=f;$('scrub').oninput()},100)};$('stop').onclick=()=>{clearInterval(animTimer);animTimer=null};
$('exportCurrent').onclick=async()=>{try{const d=await api('/api/export/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frame:+$('currentFrame').value})});log('已导出 '+d.filename);window.location=d.download}catch(e){log(e.message)}};$('exportAll').onclick=async()=>{try{await api('/api/export/all',{method:'POST'});const poll=setInterval(async()=>{const d=await api('/api/export/progress');$('progress').textContent=d.progress>=0?`导出进度 ${d.progress}%`:'';if(d.progress>=100){clearInterval(poll);log('全部帧导出完成');window.location='/api/download/all'}} ,300)}catch(e){log(e.message)}};
init3d();refresh();
</script></body></html>'''


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5011, debug=False, threaded=True)
