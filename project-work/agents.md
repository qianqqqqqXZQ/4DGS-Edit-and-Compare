# Project Notes

## Overview

This is a Flask and Three.js Part-Level 4DGS Animation Editor. Backend state, parsing,
animation, export, and API routes are in `app.py`; the active browser UI is
`static/editor.html`. `app.py` still contains a legacy embedded `HTML_PAGE` fallback, but
the root route serves the static editor when it is present.

## Layout

- `README.md`: Polished English-first GitHub overview covering Part editing, 4DGS workflows, Cloud A/B comparison, evaluation, setup, and exports.
- `app.py`: Flask application, `STATE`, PLY/PT readers, Part/keyframe/4DGS APIs, and fallback UI.
- `static/`: local Three.js r128 and OrbitControls assets.
- `static/editor.html`: active Three.js editor, binary point-cloud parser, immutable source-position preview, and responsive controls.
- `generated/`: exported PT frames and archives.
- `project-work/`: maintained planning and project-reference documents.
- `requirements.txt`: Flask, NumPy, plyfile, and PyTorch dependencies.

Documentation conventions:

- Keep planning/reference notes in `project-work/`.
- Keep generated exports in `generated/`.
- Keep the English README section first; link to the Chinese section with the language selector at the top.

## Run And Test

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 app.py
py -3.13 -m py_compile app.py
```

Ubuntu/Debian equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

The server listens on `http://localhost:5011`.

Documentation verification:

```powershell
py -3.13 -m py_compile app.py
git diff --check
```

Export path inputs are resolved on the server with user-home and environment-variable expansion,
so Linux inputs such as `~/Desktop/delete` produce `~/Desktop/delete.pt` for current-frame export.

New workspaces default to one timeline frame. `POST /api/export` treats a one-frame request's `output_dir`
value as a file path (adding `.pt` when needed), so `~/Desktop/new` writes `~/Desktop/new.pt`; multi-frame
requests retain directory output with `frame_0000.pt`, `frame_0001.pt`, and so on.

## Linux Compatibility (2026-08-17)

- The backend has no Windows-specific paths or system commands. `app.py` listens on
  `0.0.0.0:5011`, so the same Flask entry point works on Linux and can be reached from the
  network when firewall rules permit it.
- `requirements.txt` uses platform-independent Python packages and PyTorch from regular PyPI. The
  documented native path targets 64-bit Ubuntu/Debian with Python 3.10+ and a glibc-based
  distribution. CUDA is not required for parsing or export.
- `Dockerfile` uses the Linux `python:3.11-slim` base image and is the portable container path.
  Docker was not installed in the current Windows environment on 2026-08-17, so a local Linux
  image build/run validation could not be performed here.

## Current API Work (2026-08-14)

The current task adds a specified SH DC color conversion, binary `GET /api/pointcloud`, and
REST-style Part APIs while retaining legacy UI routes. State changes hold `STATE_LOCK`; static
point clouds use global arrays plus `part_id_array`, while source 4DGS frames are held in
`STATE['4dgs_parts']`. `GET /api/pointcloud` is intentionally source-data-only: it does not
apply keyframe transforms, emits little-endian count/xyz/rgb/part-id arrays, and colors unassigned
static points from SH DC. Verify this work using Flask's test client and in-memory PLY/PT fixtures.

## API Contract Notes (2026-08-15)

- `GET /api/frame/<frame>` emits `count + xyz` for static-only workspaces and adds RGB plus Part ids when a 4DGS Part exists. Keyframe preview transforms remain client-side.
- `POST /api/export` serializes in a background thread using `export_active`, `export_progress`, and `export_done`; `POST /api/export_current` applies Part transforms before writing a `.pt` file.
- Part deletion is intentionally split: `DELETE /api/parts/<pid>` is non-destructive and removes
  only the Part assignment/animation, while `DELETE /api/parts/<pid>/vertices` destructively removes
  a static Part's vertices, compacts all point attributes, and remaps remaining Part indices.
- Verification is the compile command plus the Flask-client regression and browser desktop/mobile checks recorded in `plans.md`.

## Frontend Contract Notes (2026-08-16)

- `static/editor.html` is the only active UI. It uses local Three.js r128 and OrbitControls files and never loads a CDN.
- `originalPositions` is immutable source geometry for every preview pass. `previewAllTransforms()` applies the active Part's degree-based slider values (converted to radians) and `/api/frame_transforms/<frame>` values to each Part using the same ZYX matrix as `app.py`.
- `setupSelectionEvents`, `onMouseDown`, `onMouseMove`, `onMouseUp`, and `performBoxSelect` implement Orbit/Select modes. Box selection projects displayed positions with `projectionMatrix * matrixWorldInverse`, rejects points behind/outside the clip volume, and supports Shift additive selection.
- 4DGS playback uses `/api/frame/<frame>` for variable-point source frames; static playback uses `/api/pointcloud?frame=<frame>`. Both are followed by `/api/frame_transforms/<frame>` and a fresh immutable preview.
- Exported checkpoints contain top-level `means`, `quats`, `scales`, `opacities`, `sh0`, `shN`, and `sh_degree`, plus a nested `splats` object for compatibility.

## Rendering Bugfix Notes (2026-08-16)

- Point-cloud `PointsMaterial` uses `sizeAttenuation: false`. The UI point-size slider is a pixel-size control; enabling attenuation here made the default value `3` world units and produced giant black point sprites that covered the viewport.
- Coordinate axes are rendered by `addThickAxes()` as red, green, and blue cylinders with `depthTest: false`, which keeps them stable over the grid and avoids origin z-fighting.

## Rendering Bugfix Notes (2026-08-17)

- Static `/api/pointcloud` responses include positions, colors, and four-byte Part IDs. The active
  editor must parse this endpoint with metadata enabled; passing `false` filled every `partIds`
  entry with `-1`, so `previewAllTransforms()` skipped all static vertices while the pivot marker
  still moved.
- `loadPointCloud()` now parses both active binary endpoints with metadata enabled. `/api/frame` is
  selected only for 4DGS workspaces, where it also carries colors and Part IDs.

## Rendering Notes (2026-08-20)

- The editor and Comparison `GridHelper` instances use a 100-unit size with 100 divisions, expanding
  the visible grid range fivefold while preserving the original 1-unit line spacing. The legacy
  embedded fallback in `app.py` is kept in sync for deployments that do not serve `static/editor.html`.

## Infinite Grid Notes (2026-08-20)

- The grid uses one 10,000-unit plane and a fragment shader for uniform 1-unit lines; there are no
  larger major cells that would change the apparent grid size.
- The plane snaps to the camera target every 1,000 units, providing an effectively infinite grid without
  allocating large line geometry.

## Grid Depth Priority Notes (2026-08-20)

- Procedural grid materials are double-sided and use `renderOrder=-10`, so the grid remains visible from
  below while staying behind scene helpers and point geometry.
- Thick coordinate axes use transparent materials, `depthTest:false`, and `renderOrder=100` in the active
  editor and Comparison scenes. Sharing the transparent render queue with the grid makes the explicit order
  authoritative, keeping axes visually above it. The legacy embedded fallback has the same double-sided,
  low-order grid settings.

## Comparison Notes (2026-08-18)

- Comparison is isolated from `STATE` through `COMPARISON_STATE`; it never changes the active Parts,
  keyframes, timeline, or export state.
- `POST /api/comparison` accepts exactly two multipart `files` (`.ply` or `.pt`) and returns metadata.
  `GET /api/comparison/a` and `/api/comparison/b` emit little-endian `count + xyz + rgb` binary payloads;
  `DELETE /api/comparison` clears the session.
- Canonical PLY/PT frames retain `colors` and `has_colors` metadata. Comparison prefers explicit RGB,
  then SH DC conversion, then neutral gray. Existing editor uploads continue using their established
  Part/SH color behavior.
- `static/editor.html` keeps `comparisonPointsA` and `comparisonPointsB` in the same Three.js scene and
  camera. Comparison mode hides editor-only controls and the original point object, supports A/B checkboxes
  plus A-only/B-only/Both shortcuts, and disposes comparison geometry/materials on exit.
- Mobile comparison mode overrides the legacy hidden left sidebar with a scrollable overlay panel so the
  two file inputs and visibility controls remain reachable at narrow widths.

## Comparison Dual view Notes (2026-08-18)

- Comparison now has four peer modes: A only, B only, Both (single viewport overlay), and Dual view.
- Dual view creates two pane-local Three.js scenes/renderers/cameras/OrbitControls only while Comparison is
  active. Cloud A and Cloud B are shown in separate panes, side-by-side on desktop and stacked on narrow screens.
- Dual panes clone the point objects while sharing the source geometries; pane materials and helper scene
  resources are disposed without releasing the main Comparison geometry twice.
- `Link cameras` is enabled by default. Camera position, quaternion, zoom, and OrbitControls target are copied
  with a recursion guard. Linked reset fits the union of both clouds; unlinked reset fits each pane separately.
- Dual view forces both clouds visible and disables the single-view visibility checkboxes. Switching back to a
  single mode restores A-only/B-only/Both visibility semantics. Exiting Comparison removes pane canvases,
  controls, renderers, and helper resources before refreshing the editor.
- Frontend verification includes Node syntax parsing, Flask compile/startup checks, desktop and `390x844`
  browser layout/lifecycle checks, console error inspection, and `git diff --check`.

## Comparison Dual View Visibility Fix (2026-08-18)

- Switching from `A only` or `B only` to Dual view previously let a pane clone inherit the source point
  object's `visible=false` state, leaving that pane without a point cloud.
- `createDualPane`, `ensureDualView`, and Dual-mode visibility refresh now force pane point objects visible.
  Single-view A/B visibility remains controlled by `comparisonVisibility`; Dual view always shows both clouds.

## Comparison Cloud Transform Export Notes (2026-08-18)

- Comparison keeps immutable base XYZ arrays and independent `{tx, ty, tz, rx, ry, rz}` transforms for Cloud A
  and Cloud B. Rotation reuses the editor's ZYX matrix and uses each cloud's base-geometry centroid as pivot.
- Transform edits update the shared Three.js geometry and recompute its bounding sphere, so both single and Dual
  view reflect the selected cloud without changing the editor `STATE` or backend comparison session.
- `Export selected .ply` downloads a binary little-endian PLY containing transformed float32 XYZ and uint8 RGB;
  it is a browser-local download and leaves original uploaded files untouched.
- Comparison transform controls expose both range sliders and numeric inputs. Translation sliders use `-5..5`
  with `.01` steps; rotation sliders use `-180..180` with `.5` degree steps, and both input types stay synchronized.

## Comparison Center Alignment Notes (2026-09-01)

- The Comparison panel's `Center align` button uses the currently displayed positions of all points in
  the selected cloud and the other cloud, so existing rotation, scale, and translation are included.
- It adds `referenceCenter - selectedCenter` to only the selected cloud's `tx/ty/tz`, preserves rotation and
  scale, and applies the result through `applyComparisonTransform()`. This keeps single view, Dual view,
  transformed PLY export, and evaluation serialization synchronized without changing backend Comparison state.
- TX/TY/TZ number and range controls are updated together. If an aligned translation exceeds the default
  `-5..5` range, the affected control bounds expand to include the value rather than clamping it.

## Comparison Evaluate Notes (2026-08-19)

- `POST /api/comparison/evaluate` keeps Comparison isolated from editor `STATE`. Cloud A is always Prediction
  (`P`) and Cloud B is always Ground Truth (`G`); the request sends the browser's current A/B transforms in
  degrees, and the backend applies the same ZYX rotation about each immutable cloud centroid.
- The endpoint accepts selected metric IDs plus `tau` and `tau_max`. It computes exact, double-chunked NumPy
  nearest neighbours to bound temporary distance buffers, then returns Accuracy, Completeness, L1 Chamfer,
  F-Score/Precision/Recall, normalized 100-sample AUC, and optional Normal Consistency.
- NC estimates unoriented normals through same-cloud `k=16` PCA. Insufficient or degenerate neighbourhoods
  yield `N/A` with an explanatory report note rather than failing the remaining selected metrics.
- Markdown reports are UTF-8 files under `generated/evaluations/`, ignored by Git. Their download route accepts
  only generated `comparison_evaluation_*.md` basenames. The cloud endpoint is constrained to `/a` and `/b`
  so it cannot shadow `/api/comparison/evaluate`.
- The Comparison panel defaults to Accuracy, Completeness, Chamfer Distance, and F-Score, with `tau=0.05` and
  `tau_max=0.10`; it downloads the returned Markdown Blob and displays a result summary after evaluation.

## Raw Tensor PT Notes (2026-08-18)

- `load_pt_bytes` accepts a raw `torch.Tensor` saved directly with `torch.save` when it is two-dimensional
  with at least three columns. Columns 0..2 become `xyz`; columns 3..5 become explicit RGB when present;
  columns 6 and above are intentionally ignored.
- Raw RGB uses the existing `_normalise_rgb` behavior, converting common 0..255 values to clipped 0..1.
- Invalid raw Tensor shapes raise `ValueError("Raw .pt tensors must have shape (N, >=3).")`; gsplat dict/list
  payload handling remains unchanged.

## NPY Point-cloud Notes (2026-08-31)

- `load_npy_bytes` accepts a numeric NumPy array shaped `(N, >=3)` with columns 0..2 as XYZ and columns 3..5
  as optional RGB. Columns after the first six are ignored; non-finite XYZ and invalid shapes are rejected.
- `.npy` uses the same canonical defaults as a raw Tensor PT cloud: identity quaternions, zero scales/opacities,
  no spherical-harmonic rest coefficients, and SH degree 0.
- Initial upload, append upload, Comparison upload, and server-side 4DGS frame directories accept `.npy`.
- Active and legacy file pickers advertise `.ply`, `.pt`, and `.npy`; generated exports remain `.pt`/PLY.

## Point-cloud Scaling Notes (2026-08-19)

- The editor keeps `editorScale` separate from Comparison state. Preview always starts from immutable
  `originalPositions`, computes the current frame centroid, applies existing Part transforms, then applies
  the global scale around that centroid. Pivot marker positions follow the same final scale.
- Editor Export Current and Export All requests automatically include the active editor scale. The backend
  validates positive finite values (maximum 100 for API safety), defaults missing values to `1.0`, and scales
  each exported frame's XYZ around its post-transform centroid without changing other Gaussian attributes.
- Comparison transforms now include `scale` (default `1.0`) in independent A/B state. The browser applies it
  around each immutable cloud centroid before rotation/translation, synchronizes existing Dual-view pane
  geometries, and uses transformed coordinates for PLY export.
- `POST /api/comparison/evaluate` accepts optional `transforms.a.scale` and `transforms.b.scale`; omitted scale
  remains backward compatible. Markdown reports include the applied scale column and invalid scales return HTTP 400.
- Scale controls use `0.1..20` with `.01` steps. The editor control is hidden in Comparison mode; Comparison
  exposes one Scale range/number pair for the selected Cloud A or Cloud B.

## Export Color Mode Notes (2026-08-19)

- Static editor state retains normalized source RGB in `STATE["colors"]` plus a per-point `color_valid` mask;
  this data survives append and destructive static-point deletion. 4DGS source frames retain their parsed RGB.
- `POST /api/export_current` and `POST /api/export` accept `color_mode` as `original` (the default) or `edited`.
  Original mode uses explicit source RGB, then SH DC display conversion, then neutral gray; edited mode uses the
  selected Part color and keeps unassigned points on the original fallback.
- Exported checkpoints write the selected RGB array as `colors` at both the top level and inside `splats`, while
  preserving `means`, `quats`, `scales`, `opacities`, `sh0`, `shN`, and `sh_degree`. The editor preview and
  Comparison export behavior are unchanged.
- `static/editor.html` adds a guarded `comparisonBackBtn` below the Comparison heading. It calls the existing
  async `exitComparison()` flow, preserving geometry disposal, backend session deletion, and editor refresh.
- Verification: Node inline-script syntax check, `py -3.13 -m py_compile app.py`, HTTP 200 smoke check, and
  `git diff --check`.

## Comparison Return Button Placement (2026-08-20)

- The guarded `comparisonBackBtn` is inserted into the top `.toolbar`, immediately before `orbitBtn`.
- CSS keeps it hidden in editor mode and visible only under `.comparison-active`; its click handler still calls
  `exitComparison()`.
