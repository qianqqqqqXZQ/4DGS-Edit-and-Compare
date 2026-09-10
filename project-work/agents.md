# Project Notes

## Overview

This is a Flask and Three.js 4DGS-Edit-and-Compare application. Backend state, parsing,
animation, export, and API routes are in `app.py`; the active browser UI is
`static/editor.html`. `app.py` still contains a legacy embedded `HTML_PAGE` fallback, but
the root route serves the static editor when it is present.

## Usability Hardening (2026-09-10)

- The active viewport defaults to original source RGB (then SH-derived color) and can switch to Part colors.
  RGB-only NPY/PT input is never reinterpreted as SH DC during import or export.
- 4DGS frame names use natural numeric sorting. The active frame loader carries a request token so a late
  response cannot overwrite a newer scrub position; every timeline track owns its matching playhead.
- `POST /api/project/download` and `POST /api/project` save/load a self-contained ZIP containing canonical
  NumPy arrays, Part metadata, keyframes, 4DGS sources, Comparison A/B clouds, and safe browser display state.
  Project archives use no pickle, enforce member/size limits, and validate before atomically replacing state.
- Destructive static-Part deletion has one in-process undo at `POST /api/undo`. It is intentionally a single
  snapshot to bound memory; a downloaded project is the durable recovery point.
- Comparison now supports metadata reads and A/B role swapping. Browser UI state survives refresh with
  localStorage while the server remains alive; a saved project is required after server restart.
- The server is still a trusted local, single-workspace process. A localStorage lease makes a second browser
  tab read-only, but it is not a substitute for server-side sessions, authentication, or multi-user isolation.

## Layout

- `README.md`: Standard English-first/Chinese GitHub documentation covering the implemented Part editing,
  4DGS, Cloud A/B comparison, evaluation, setup, API, and export workflows.
- `app.py`: Flask application, `STATE`, PLY/PT readers, Part/keyframe/4DGS APIs, and fallback UI.
- `static/`: local Three.js r128 and OrbitControls assets.
- `static/editor.html`: active Three.js editor, binary point-cloud parser, immutable source-position preview, and responsive controls.
- `generated/`: exported PT frames and archives.
- `project-work/`: maintained planning and project-reference documents.
- `requirements.txt`: Flask, NumPy, plyfile, and PyTorch dependencies.

## Trusted Input And Local Boundary (2026-09-10)

- This application has one global in-memory workspace and is deliberately a single-user local tool. The
  default listener is `127.0.0.1:5011`; `EDITOR_HOST` and `EDITOR_PORT` override the bind address and port.
  An operator who explicitly exposes it to a LAN must provide authentication and network isolation, because
  the application does not add either multi-user sessions or authorization.
- `EDITOR_ALLOWED_PATHS` defines the roots accepted by server-path APIs, separated by the host platform's
  path separator (`;` on Windows and `:` on POSIX). With no setting, only the repository root is allowed.
  `_resolve_user_path()` expands variables, rejects `..`, canonicalizes absolute paths with `realpath`, and
  rejects paths and symlink targets outside those roots. `/api/upload_4dgs`, `/api/export`,
  `/api/export_current`, and legacy `/api/export/current` plus `/api/export/all` all use this check.
- `load_pt_bytes()` uses `torch.load(..., weights_only=True)` only. It accepts safe tensors/scalars/strings
  and nested list/tuple/dict checkpoint data that resolves to a raw Tensor, flat gsplat dictionary, nested
  `splats`, or non-empty `frames` format. It never falls back to arbitrary pickle loading.
- Canonical input validation requires finite, non-empty `(N, 3)` XYZ data. Present quaternion, scale,
  opacity, RGB, SH DC, and SH-rest arrays must have a compatible `N`; malformed arrays are rejected instead
  of being truncated or zero-padded. Upload temporary directories are removed in `_load_uploaded_pointclouds()`
  on both parse success and failure. Existing `generated/` exports and evaluation reports are retained; a
  future retention policy can manage those persistent user artifacts without changing current behavior.
- Use `D:\Develop\Python\CPython\Python313\python.exe` directly in this workspace when the `py -3.13`
  launcher cannot locate its installed runtime. The normal project command remains `py -3.13` elsewhere.

## Transform Numeric Input Contract (2026-09-09)

- The active UI in `static/editor.html` uses text inputs for Part TX/TY/TZ/RX/RY/RZ, Comparison A/B
  TX/TY/TZ/RX/RY/RZ/Scale, and editor global Scale. `parseNumericText()` accepts finite complete values,
  while incomplete drafts such as `-`, `-.`, `.`, `1.`, `1e`, and `1e-` remain in the DOM without changing
  the last valid transform.
- Canonical state is intentionally separate from DOM drafts: `partTransformUiValues` feeds `uiTransform()`,
  `comparisonTransformUiValues.a/b` feeds the Comparison UI, and `comparisonTransforms.a/b` feeds geometry,
  export, and evaluation. `editorScale` feeds editor preview and export. Programmatic setters and reset/frame/
  cloud switches update the canonical value, text draft, slider, and label through the same setters.
- Finite numeric drafts preview immediately. Blur or Enter commits: invalid/empty text restores the last valid
  value; rotations clamp to `-180..180` degrees; Scale clamps to `.1..20`; TX/TY/TZ remain any finite value.
  Translation range min/max values expand when needed and are retained for the lifetime of the control. Slider
  input is always a complete commit and remains bidirectionally synchronized.
- UI rotations are degrees, while Part/Comparison transform objects and backend APIs continue to use radians;
  Comparison evaluation serializes degrees as before. Numeric formatting removes only unnecessary trailing zeros
  and never truncates valid precision such as `2.375`.
- Each transform control has one input handler path. `wireComparisonEvents()` owns Comparison transform fields,
  `wireScaleEvents()` owns only editor Scale, and `applyComparisonTransform()` stores canonical Comparison state
  before checking whether geometry is currently loaded. This prevents pre-load edits from being discarded.

Validation for this contract:

```powershell
node --check <temporary inline editor script>
py -3.13 -m py_compile app.py
py -3.13 -m unittest discover -s tests -p "test_*.py"
git diff --check
```

The browser smoke uses `generated/frame_0000.pt` and `generated/frame_0001.pt`; pytest is optional and may be
unavailable in the configured Python environment.

## Circular Point Sprite Rendering (2026-09-09)

- Point clouds still use `THREE.PointsMaterial` with vertex colors, pixel-sized points,
  and `sizeAttenuation: false`. `createPointMaterial(size)` is the single factory used by
  the main editor, Comparison A/B objects, and Dual view clones in `static/editor.html`.
- The factory initializes `material.extensions` for Three.js r128, enables derivatives, and
  injects a small `gl_PointCoord` distance test into the fragment shader. `fwidth` plus
  `smoothstep` provides a lightly anti-aliased circular edge; fragments outside the radius
  are discarded. The same factory and shader hook are mirrored in the legacy `HTML_PAGE`
  inside `app.py`.
- The point-size slider changes `.size` on the main, Comparison, and Dual view materials;
  it does not rebuild buffers or perform per-frame JavaScript work. Dual view clones use a
  fresh material but share source geometry, and the existing disposal path releases each
  renderer/material while leaving shared geometry ownership with the source object.
- Browser smoke checks on the available point-cloud fixtures compiled all views without
  WebGL warnings and showed no responsive-layout overflow or perceptible interaction delay.
  If a target browser/GPU reports shader compilation failures or clearly visible frame drops,
  remove the `onBeforeCompile` hook and `transparent` circular path and restore ordinary
  `PointsMaterial` square rendering as the safe fallback.

## Point-depth Visibility Fix (2026-09-09)

- Rounded point sprites keep alpha blending for their anti-aliased circular edge, but the shared
  factory now explicitly sets `depthTest: true`, `depthWrite: true`, and `alphaTest: .001`. This
  lets opaque point interiors write the depth buffer, preventing Cloud A/B (and points within one
  cloud) from visually showing through nearer points in Comparison mode.
- The active `static/editor.html` and legacy `app.py` `HTML_PAGE` keep the same material options and
  shader cache key. This applies equally to the editor, Comparison overlay, and Dual-view materials.

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

Path-based export inputs are resolved only inside `EDITOR_ALLOWED_PATHS`; user-home and environment-variable
expansion is supported only when the resulting canonical path remains in an allowed root.

## Browser Download Export Notes (2026-09-09)

- The active `static/editor.html` no longer asks for an editor export path. `Export Current`
  downloads a transformed `.pt` through `/api/export_current/download`; `Export Frames` downloads
  a ZIP of `frame_0000.pt`, `frame_0001.pt`, and so on through `/api/export/download`.
- These browser-download routes accept the same `scale` and `color_mode` values as the path-based
  routes, plus optional JSON `filename`. The editor's current-frame and all-frames dialogs pass their
  optional name fields to their respective download routes. The older `/api/export_current` and
  `/api/export` endpoints remain available for API clients that explicitly need server-side output paths.
- `_clean_download_filename` rejects path separators/control characters and ensures the selected `.ply`,
  `.pt`, `.npy`, or `.zip` extension is applied exactly once. Blank names retain source-based defaults:
  `*.frame_XXXX.pt`, `*.frames.zip`, or `*.transformed.<ext>` for Comparison exports.
- `ensureComparisonFilenameControl()` retains the compact Comparison layout; the editor dialog fields are
  explicit markup. Browser download handling reads `Content-Disposition`, falls back to a deterministic
  name, revokes Blob URLs after click, and restores button state after errors.
- Browser smoke on 2026-09-09 used the local `frame_0000.pt` and `frame_0001.pt` fixtures: the
  editor downloaded the current frame and ZIP, Comparison reached `Ready` with 6/4 points, and
  `aligned_result` produced `aligned_result.ply` with no console warnings or errors.
- Browser smoke on 2026-09-10 confirmed the optional filename fields appear in both editor download dialogs
  without layout overflow. Backend regression verifies a requested `.zip` current-frame name becomes `.pt`, a
  requested `.pt` archive name becomes `.zip`, and both editor download routes reject filename paths.

New workspaces default to one timeline frame. `POST /api/export` treats a one-frame request's `output_dir`
value as a file path (adding `.pt` when needed), so `~/Desktop/new` writes `~/Desktop/new.pt`; multi-frame
requests retain directory output with `frame_0000.pt`, `frame_0001.pt`, and so on.

## Linux Compatibility (2026-08-17)

- The backend has no Windows-specific paths or system commands. `app.py` defaults to
  `127.0.0.1:5011` on Linux and Windows; an operator must explicitly set `EDITOR_HOST` before network
  exposure and must supply the missing authentication/network isolation controls.
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

## Comparison Layout And Export Notes (2026-09-01)

- `static/editor.html` keeps `comparisonBtn` as the first toolbar button and uses a static `comparisonBackBtn`.
  In editor mode the back button is hidden; in Comparison mode every toolbar button except Back to Editor is
  hidden, so the mode has a clear enter/exit boundary.
- Comparison mode uses a two-column app grid with a desktop-only `comparisonResizer`. Its width is clamped to
  `220..520px` while preserving at least `360px` for the viewport, adjusted with Pointer Events or 10px arrow
  key steps, and stored under the `comparison-left-width` local-storage key. Mobile keeps the overlay panel and
  hides the divider.
- `POST /api/comparison/export` reads isolated `COMPARISON_STATE`, applies the submitted degree-based transform
  with `_comparison_transformed_xyz()`, and uses `_comparison_colors()` for explicit RGB, SH-derived, or neutral
  fallback colors. The response is an in-memory attachment named `<source>.transformed.<format>`.
- Comparison export formats are generic point-cloud payloads: binary little-endian PLY with XYZ float32/RGB
  uint8, NPY float32 `(N, 6)` with XYZ+RGB where RGB is `[0,1]`, or a raw `torch.float32` `(N, 6)` tensor.
  These exports intentionally do not preserve Gaussian attributes.

## Comparison Point-count HUD Notes (2026-09-07)

- `static/editor.html` renders one `comparisonPointCounts` HUD in the main Comparison viewport,
  including Dual view; it is not duplicated inside either Dual pane.
- `renderComparisonPointCounts()` reads only `comparisonClouds.a/b.n_vertices`, so displayed values
  remain the original uploaded point counts and do not change with transforms, alignment, ICP/evaluation,
  or visibility/layout changes.
- Missing metadata renders `Cloud A: -- pts` and `Cloud B: -- pts`. Comparison cleanup resets the
  metadata and refreshes the HUD, while the `.comparison-active` CSS rule hides it outside Comparison.
- The HUD uses `toLocaleString()`, `pointer-events: none`, and a viewport-relative `z-index` above
  the point/canvas layers. Narrow layouts reduce padding and font size while reserving horizontal space.

## Comparison Evaluation Notes (2026-09-08)

- POST /api/comparison/evaluate uses required scipy.spatial.cKDTree exact Euclidean queries. It evaluates
  only the directional nearest-neighbour arrays needed by the selected metrics, preserving Cloud A as prediction
  and Cloud B as ground truth.
- Normal Consistency queries exact same-cloud neighbours (k=16) and computes batched PCA normals; insufficient
  or degenerate local geometry remains N/A.
- The response keeps existing fields and adds runtime_seconds plus query_engine. Generated reports are compact,
  bilingual Chinese/English Markdown: prediction/ground-truth filenames and point counts, thresholds/runtime,
  then the selected-metrics table. F-Score includes Precision/Recall in its value cell; an unavailable Normal
  Consistency includes its explanation only in that metric row. Dynamic report values escape pipes, backslashes,
  and line breaks.
- Run the focused regression with py -3.13 -m unittest discover -s tests -p "test_*.py"; run
  py -3.13 -m py_compile app.py, frontend syntax checks, and git diff --check before marking changes complete.

## Comparison Loading Feedback (2026-09-09)

- `static/editor.html` keeps Comparison metadata separate from editor state. The load flow is
  synchronous on the server, so the UI reports `Preparing Cloud A and Cloud B...` immediately,
  then updates through upload, metadata, geometry download, parsing, and `Ready` states.
- `comparisonUploadBtn` is disabled for the complete async operation and re-enabled in `finally`,
  including malformed-file and HTTP-error paths. Error text is prefixed with `Comparison load failed:`.
- A restarted Flask process is required after editing `static/editor.html`; the root route serves the
  static page, while `app.py` remains the legacy embedded fallback.
- Browser verification fixture: `generated/frame_0000.pt` (6 points) and `generated/frame_0001.pt`
  (4 points). Invalid `README.md` confirms failure recovery.

## Usability And Risk Audit (2026-09-10)

- The detailed, non-mutating audit is `generated/usability-audit-2026-09-10.md`. Treat its P1 items as
  correctness work before feature expansion: capture the Part ID for delayed Pivot saves, reject stale frame
  responses, use natural numeric 4DGS frame ordering, and align the timeline playhead with `.track-line`.
- Do not conflate explicit RGB with Gaussian SH DC: raw NPY/PT columns 3..5 are RGB. The current
  `_normalise_frame()` includes RGB aliases in its `sh0` fallback and needs a semantic correction plus tests.
- The UI still has duplicate export binding layers: the last `wireBrowserExportEvents()` assignment wins, while
  older handlers reference absent `currentPath`/`allPath`. Consolidate this before changing export behavior.
- The Flask globals intentionally implement one in-memory local workspace. Browser refresh loses frontend-only
  scale/Comparison transforms and server restart loses the workspace; add project persistence/undo before
  treating the editor as suitable for long-running production editing sessions.
