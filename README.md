# 4DGS-Edit-and-Compare

**4DGS-Edit-and-Compare is a workspace for aligning, editing, and evaluating point clouds and 4D Gaussian Splatting (4DGS) data.** It combines a Three.js/WebGL viewport with a Flask backend, making it practical to correct the pose of individual scene components, animate edits over time, compare two reconstructed assets, and export the resulting data without leaving one workflow.

The project was designed for reconstruction and LiDAR-alignment work, where a model may need to be translated, rotated, scaled, inspected against a reference cloud, and saved back into a reusable format.

## Highlights

- **Part-level editing:** Select static vertices and group them into editable Parts. Each Part has an independent name, color, pivot, translation, and rotation.
- **Keyframed 4D editing:** Animate Part transforms along a timeline with linear or Catmull-Rom interpolation, then preview the result in the browser.
- **4DGS support:** Load `.ply` point clouds, `.npy` arrays, gsplat-style `.pt` checkpoints, raw PyTorch tensors, or a directory of `.pt`/`.npy` frames as a looping 4DGS Part.
- **Cloud-to-cloud comparison:** Load Cloud A and Cloud B in an isolated comparison workspace, view them individually, overlaid, or in synchronized dual viewports.
- **Alignment and evaluation:** Apply independent translation, ZYX rotation, and centroid-preserving scale to each comparison cloud. Generate Markdown reports with Accuracy, Completeness, Chamfer Distance, F-Score, AUC, and optional normal consistency.
- **Export-ready output:** Export a transformed comparison cloud as binary `.ply`, a raw point-cloud `.pt`, or an `.npy` array, plus the current editor frame as a Gaussian `.pt` or every timeline frame as a batch export. New workspaces default to one frame.

## What You Can Do

1. Upload one or more static `.ply`, `.npy`, or `.pt` point clouds. Each uploaded file can become an editable Part.
2. Use rectangle selection to isolate vertices, create new Parts, set a centroid pivot, and make precise pose adjustments.
3. Add keyframes and scrub or play the timeline to inspect interpolated motion.
4. Import a server-side 4DGS frame directory and combine dynamic content with static edited geometry.
5. Switch to Comparison mode to align two independent point clouds, inspect them in dual view, calculate reconstruction metrics, and export the aligned result as `.ply`, `.pt`, or `.npy`.

## Supported Inputs

| Format | Supported content |
| --- | --- |
| `.ply` | XYZ coordinates, optional RGB, Gaussian rotations, scales, opacity, and spherical-harmonic attributes. |
| `.npy` | Numeric array shaped `(N, >=3)`; columns 1-3 are XYZ, columns 4-6 are optional RGB, and later columns are ignored. |
| `.pt` checkpoint | Flat or nested gsplat-style data with fields such as `means`, `quats`, `scales`, `opacities`, `sh0`, and `shN`. |
| Raw `.pt` tensor | A two-dimensional tensor shaped `(N, >=3)`. The first three columns are XYZ and columns 4-6, when present, are interpreted as RGB. |
| 4DGS directory | A directory of filename-sorted `.pt` or `.npy` frames, imported as an animated Part with optional looping. |

For data with spherical harmonics but no explicit RGB, the viewport derives display color from the DC coefficient. The editor preserves Gaussian attributes when exporting `.pt` data.

## Comparison Metrics

Comparison mode treats **Cloud A as the prediction** and **Cloud B as the ground truth**. The evaluation endpoint applies the current independent transforms before computing the selected metrics:

- Accuracy and Completeness
- L1 Chamfer Distance
- F-Score, Precision, and Recall at a configurable threshold
- Area under the F-Score curve (AUC)
- PCA-estimated Normal Consistency, where the input neighborhoods are sufficient and non-degenerate

Reports are saved as Markdown under `generated/evaluations/` and downloaded automatically by the interface.

## Comparison Export

Comparison mode is a separate workspace. Its toolbar entry is the leftmost editor action; once active,
the top toolbar keeps only **Back to Editor**. On desktop, drag the divider at the right edge of the
Comparison panel to resize it. The width is remembered locally and the divider is hidden on mobile.

`POST /api/comparison/export` exports the selected Cloud A or Cloud B after the current centroid-based
scale, ZYX rotation, and translation. The format selector supports:

- `.ply`: binary little-endian XYZ float32 plus RGB uint8.
- `.npy`: float32 array shaped `(N, 6)` with XYZ followed by RGB in `[0, 1]`.
- `.pt`: raw `torch.float32` tensor shaped `(N, 6)` with the same XYZ+RGB columns as `.npy`.

Comparison `.pt` and `.npy` exports are generic point-cloud files; they do not preserve Gaussian
quaternions, scales, opacity, or spherical-harmonic attributes.

## Architecture

| Path | Responsibility |
| --- | --- |
| `app.py` | Flask application, PLY/PT parsers, editor and comparison state, transform math, REST endpoints, evaluation, and export logic. |
| `static/editor.html` | The active Three.js editor, viewport renderer, selection interactions, timeline, and comparison UI. |
| `static/three.min.js` | Local Three.js runtime. |
| `static/OrbitControls.js` | Local orbit-camera controls. |
| `generated/` | Default output location for exported frames, archives, and evaluation reports. |
| `project-work/` | Project plans and development notes. |

## Quick Start

### Local Python

Python 3.10 or later is recommended. The default requirements install CPU-compatible PyTorch; CUDA is not required to parse or export supported data.

```bash
git clone <repository-url>
cd 3D-editor
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and start the application:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open [http://localhost:5011](http://localhost:5011) in a WebGL-capable browser.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
git clone <repository-url>
cd 3D-editor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

The server listens on `0.0.0.0:5011`, so it can also be reached on a local network at `http://<host-ip>:5011` after allowing TCP port `5011` through the host firewall.

### Docker

```bash
docker build -t 3d-editor .
docker run --rm -p 5011:5011 3d-editor
```

To import a 4DGS directory in Docker, mount it into the container and enter the mounted path in the **4DGS Dir** dialog:

```bash
docker run --rm -p 5011:5011 -v /path/to/frames:/data/frames 3d-editor
```

## Editing Workflow

1. Select **Upload** to replace the current static workspace, or **Add Files** to append point clouds. `.npy` files use the same `(N, >=3)` convention described above.
2. Enter **Select** mode, drag a rectangle around static vertices, and choose **Create Part**.
3. Select a Part to edit its name, color, pivot, translation, rotation, and global editor scale.
4. Save a keyframe at the current timeline position; scrub or play to inspect the motion.
5. Use **Export Current** for one transformed frame or **Export All** for the complete timeline.

Removing a static Part is non-destructive: its points remain in the workspace as unassigned vertices. The separate destructive action permanently removes the selected static Part and its vertices, then remaps the remaining Part indices.

## REST API

The browser interface is backed by a small JSON/binary REST API. The principal routes are:

- `POST /api/upload`, `POST /api/upload_append`, and `POST /api/upload_4dgs`
- `GET /api/state`, `GET /api/pointcloud`, and `GET /api/frame/<frame>`
- `GET/POST/PUT/DELETE /api/parts...` for Part management and vertex assignment
- `GET/POST/DELETE /api/keyframes/<pid>...` and `GET/PUT /api/settings`
- `POST /api/comparison`, `GET /api/comparison/a`, `GET /api/comparison/b`, `POST /api/comparison/evaluate`, and `POST /api/comparison/export`
- `POST /api/export`, `GET /api/export/status`, and `POST /api/export_current` (`color_mode` accepts `original` or `edited`; original source RGB is the default)

Binary point-cloud endpoints return compact XYZ, RGB, and Part-ID payloads for the local renderer. Comparison data is deliberately kept separate from the active editor workspace, so comparison uploads never alter Parts, animation tracks, or editor exports.

## Development Checks

```bash
python -m py_compile app.py
git diff --check
```

The project also uses Flask test-client coverage for parser, API, transform, evaluation, and export regressions. Generated artifacts belong under `generated/` to keep source changes and outputs separate.

## Background

This tool grew out of 3D reconstruction work where reconstructed assets were often misaligned with coordinate axes or LiDAR ground truth. General-purpose viewers can inspect point clouds, but they do not always provide an efficient workflow for part-level correction, direct A/B comparison, animated pose adjustment, and 4DGS-oriented export. 3D-Editor brings those operations into one focused, browser-accessible workspace.
