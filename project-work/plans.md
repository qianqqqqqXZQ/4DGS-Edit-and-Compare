# Part-Level 4DGS Animation Editor Plan

## Current Request: Comparison center alignment (2026-09-01)

- [x] Create a recoverable Git checkpoint before the Comparison center-align implementation (`e74ba89`).
- [x] Add a Comparison-only `Center align` button that moves the selected cloud's current centroid to the other cloud's current centroid.
- [x] Preserve existing rotation/scale values, synchronize TX/TY/TZ controls, expand translation bounds when alignment exceeds the default slider range, and update Dual view geometry.
- [x] Run frontend syntax parsing, Python compilation, functional centroid/transform regression, diff validation, and focused code review.

2026-09-01 verification completed:

- `py -3.13 -m py_compile app.py`
- Active inline scripts parsed with Node `new Function`.
- Functional DOM/Three stub regression confirmed A-to-B and B-to-A center alignment, current-position centroid math, transform serialization, translation-bound expansion, Dual view synchronization, and disabled state when a cloud is missing.
- `git diff --check`
- Focused review confirmed the feature is frontend-only and reuses the existing Comparison transform path for preview, export, and evaluation.

## Current Request: Export Original or Edited Colors (2026-08-19)

- [x] Create a recoverable Git checkpoint before changing export color handling (`1d21d81`).
- [x] Preserve per-point source RGB through static uploads, append operations, static deletion, and 4DGS source frames.
- [x] Add `color_mode` support to current-frame and batch export APIs, defaulting to `original` with explicit RGB, SH DC, and neutral-gray fallback.
- [x] Write selected RGB values to both top-level and nested `splats.colors` in exported `.pt` checkpoints without changing Gaussian SH attributes.
- [x] Add default-original color selectors to both editor export dialogs and send the selected mode in their requests.
- [x] Run compile, export regression, frontend syntax, upload-path, batch-export, diff, and focused-review checks.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- In-memory export regression for explicit RGB, SH/neutral fallback, static Part edited colors, 4DGS Part colors, `.pt` top-level/nested `colors`, and invalid `color_mode` rejection.
- Browser-script syntax parsing, multipart upload/export API regression, asynchronous batch export regression, and `git diff --check`.
- Focused review of per-point color validity, static/4DGS aggregation, color-mode capture by the export worker, and unchanged preview/Comparison behavior.

## Current Request: English Repository Description (2026-08-19)

- [x] Inspect the active Flask and Three.js implementation to establish the supported editing, comparison, evaluation, and export capabilities.
- [x] Create a recoverable Git checkpoint before replacing repository documentation (`50b742c`).
- [x] Rewrite the root README as a polished, English-first GitHub repository description that reflects the implemented product.
- [x] Verify documentation consistency, review the changed files, and record the final validation.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- README content check confirmed the product description, Part editing, 4DGS, comparison, metrics,
  setup, REST API, and background sections. The rewritten README contains no non-ASCII characters.
- `git diff --check`
- Focused documentation review matched every named workflow to the active Flask routes and Three.js UI,
  including keyframe interpolation, A/B dual view, centroid-based transforms, evaluation, and both export paths.

## Baseline

- [x] Establish `project-work/` for working documents and `generated/` for generated exports.
- [x] Implement the initial Flask editor, PLY/PT parsing, Part editing, keyframe tracks, 4DGS import, and exports.
- [x] Verify the baseline with Python compilation and Flask test-client coverage.

## Current Request: Color Handling and HTTP API Contract (2026-08-14)

- [x] Add the specified SH-to-RGB conversion and fixed Part color palette.
- [x] Implement compliant initial and append point-cloud uploads, including SH-degree padding.
- [x] Implement server-directory 4DGS upload and 4DGS/static state initialization.
- [x] Implement binary point-cloud payload and REST-style Part management APIs.
- [x] Run compilation plus API regression coverage, review the changed code, then update this checklist.

## Current Request: Complete HTTP API and Editor Contract (2026-08-15)

- [x] Create a Git checkpoint before the implementation changes.
- [x] Complete REST-style keyframe, settings, frame, export, and current-export endpoints.
- [x] Correct binary frame/point-cloud payloads and state/export concurrency behavior.
- [x] Replace the damaged embedded editor page with `static/editor.html`, covering the requested upload, selection, transform, timeline, and modal workflows.
- [x] Run compilation, API regression coverage, browser rendering checks, and a focused code review.

## Run

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 app.py
```

Open `http://localhost:5011`.

## Verification

```powershell
py -3.13 -m py_compile app.py
```

2026-08-15 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test-client regression for initial/append uploads, SH normalization, REST Part and keyframe operations, static/4DGS binary payloads, settings, and both export paths.
- Browser checks at desktop and `390x844` mobile viewports: Three.js canvas rendered, controls appeared in their responsive layout, and no console errors were reported.

## Current Request: Project Documentation (2026-08-15)

- [x] Create a Git checkpoint before documentation changes.
- [x] Rewrite the root README with an English-first language switch and a Chinese translation.
- [x] Document the current structure, Quick Start, workflow, supported data, API entry points, Background, and Acknowledgements.
- [x] Synchronize `project-work/agents.md` with the active static editor and run a documentation/code review.
- [x] Run compilation and repository checks after the documentation changes.

2026-08-15 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test client `GET /` check confirming the active `static/editor.html` page is served.
- Explicit UTF-8 README section checks for both language sections and required headings.
- `git diff --check`

## Current Request: Chinese Ubuntu Quick Start (2026-08-18)

- [x] Create a recoverable Git checkpoint before the documentation change (`00e5c42`).
- [x] Add Chinese Ubuntu/Debian instructions to the README, including virtualenv setup,
  browser URL, LAN access, and UFW port configuration.
- [x] Run documentation/code checks and complete a focused documentation review.

2026-08-18 verification completed:

- `python -m py_compile app.py`
- UTF-8 README content checks for the Ubuntu/Debian commands and URLs.
- `git diff --check`
- Focused review confirmed the documented local URL matches `app.py` (`0.0.0.0:5011`)
  and the LAN/UFW instructions match the server's network behavior.

## Current Request: Frontend transform, selection, timeline, and export contract (2026-08-16)

- [x] Create a recoverable Git checkpoint before the implementation changes.
- [x] Replace the active editor UI with explicit Orbit/Select modes, crosshair box selection, Shift additive selection, yellow selected points, and clip-space projection checks.
- [x] Implement immutable `originalPositions` preview with ZYX Euler rotation, per-Part backend transforms, active slider override, and translation-only Pivot marker motion.
- [x] Implement Part loading/list rendering, 4DGS labels, Pivot editing/centroid reset, degree-based transform sliders, keyframe operations, per-Part timeline markers, and 20 FPS playback.
- [x] Connect static and 4DGS frame endpoints, background export polling, and visible fetch error handling to the local Three.js r128 assets.
- [x] Enforce unloaded-workspace 400 responses for frame/point-cloud/transform endpoints and expose exported `.pt` fields at top level plus nested `splats` compatibility.
- [x] Run JavaScript syntax, Python compilation, Flask API regression, 4DGS variable-point/export regression, startup HTTP, and `git diff --check` verification.

## Bugfix: black viewport on initial point-cloud render (2026-08-16)

- [x] Reproduce the black viewport with a real uploaded `.pt` file and inspect the rendered canvas.
- [x] Identify the cause as `PointsMaterial.sizeAttenuation` interpreting the default point size as world units.
- [x] Render point sizes in pixels with `sizeAttenuation: false` and verify the grid/points at desktop and mobile viewport sizes.

## Bugfix: axis-line flicker (2026-08-16)

- [x] Replace the thin `AxesHelper` with thicker red/green/blue cylinder axes.
- [x] Disable depth testing and depth writes for the axes to prevent grid z-fighting at the origin.
- [x] Verify the empty editor viewport visually and confirm no browser console errors.

## Current Request: Linux Quick Start (2026-08-17)

- [x] Inspect the server, dependencies, and container definition for platform-specific constraints.
- [x] Add an Ubuntu/Debian Linux Quick Start to the English README section.
- [x] Run available validation checks, review the documentation change, and record the Linux verification boundary.

2026-08-17 verification completed:

- `python -m py_compile app.py`
- Flask test client `GET /` and `GET /static/editor.html` smoke checks (both returned HTTP 200).
- README Linux Quick Start content check and `git diff --check`.
- Static platform review found no Windows-specific backend paths or commands. Docker is not
  installed and WSL has no Linux distribution in the current environment, so a native Linux or
  container run was not available for this checkout.

## Bugfix: static Part transform preview (2026-08-17)

- [x] Trace the static point-cloud load path and compare its binary metadata contract with the
  browser parser.
- [x] Preserve static Part IDs in the active editor so translation and rotation are applied to
  point positions, not only to the pivot marker.
- [x] Run Python, JavaScript, API/coordinate, page smoke, and diff checks; review the focused
  frontend change and record the browser upload-tool limitation.

2026-08-17 verification completed:

- `py -3.13 -m py_compile app.py`
- Active `static/editor.html` script parsed with `new Function`.
- Flask test client regression confirmed `/api/pointcloud` returns Part IDs and a keyframe with
  translation plus 90-degree rotation produces the expected transformed coordinates.
- Local browser opened `http://127.0.0.1:5011/`, rendered the active editor DOM with no startup
  console errors. Automated hidden-file chooser upload timed out, so no visual point movement
  assertion was made through the browser.
- `git diff --check`

## Current Request: Isolated point-cloud Comparison (2026-08-18)

- [x] Create a Git checkpoint before Comparison implementation (`afbb16e`).
- [x] Add isolated two-cloud Flask session APIs with binary XYZ/RGB payloads and strict upload validation.
- [x] Preserve explicit PLY/PT RGB and fall back to SH-derived or neutral gray display colors.
- [x] Add the Three.js Comparison mode with shared camera, A/B visibility toggles, quick combinations, and point-size control.
- [x] Keep Comparison state separate from editor Parts/keyframes and restore the editor on exit.
- [x] Run backend regression, JavaScript syntax, desktop/mobile browser checks, and focused code review.

2026-08-18 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test client coverage for two-color PLY, colorless PLY fallback, explicit-color PT, SH-only PT,
  binary payload lengths, invalid file counts, delete behavior, and unchanged `/api/state`.
- Active `static/editor.html` script parsed with `new Function` / Node syntax check.
- Local browser at desktop and `390x844` mobile viewports: Comparison controls rendered, mobile panel remained accessible,
  two generated PT files uploaded through file chooser, point counts and color-source metadata displayed,
  B-only visibility toggled, and exit cleanup restored the editor UI.
- `git diff --check`

## Current Request: Comparison Dual view (2026-08-18)

- [x] Create a recoverable Git checkpoint before the Dual view implementation (`2ff9a1f`).
- [x] Add the four-mode Comparison UI with a responsive A/B Dual view layout.
- [x] Add two independent Dual view renderers/cameras with optional camera linking and reset behavior.
- [x] Preserve single-view A-only/B-only/Both behavior and clean up Dual view resources on exit.
- [x] Run syntax, backend/API, browser layout, lifecycle, and diff checks; complete a focused code review.

2026-08-18 verification completed:

- `py -3.13 -m py_compile app.py`
- Active `static/editor.html` script parsed with Node `--check`.
- Flask startup smoke check served the editor; existing Comparison API contract remained unchanged.
- In-app browser desktop check confirmed four modes, two renderer canvases, linked/unlinked camera controls,
  reset behavior, single-view restoration, Dual renderer cleanup, and no console warnings/errors.
- In-app browser `390x844` check confirmed stacked panes, no horizontal overflow, and the mobile Comparison
  panel no longer obscures the panes.
- `git diff --check`
- Focused review covered renderer disposal, shared point geometry ownership, camera sync recursion guards,
  mode transitions, and responsive CSS ordering.

## Current Request: Raw Tensor PT support (2026-08-18)

- [x] Create a recoverable Git checkpoint before adding raw Tensor parsing (`d9a88df`).
- [x] Extend `load_pt_bytes` to accept raw `torch.Tensor` payloads with shape `(N, >=3)`.
- [x] Map the first three columns to coordinates, the next three columns to optional RGB, and ignore later columns.
- [x] Reuse RGB normalization for raw tensors and reject invalid tensor shapes with a clear error.
- [x] Run raw Tensor parsing tests, compilation, repository checks, and a focused code review.

2026-08-18 verification completed:

- `py -3.13 -m py_compile app.py`
- In-memory `torch.save`/`load_pt_bytes` checks for `(N,7)` RGB plus ignored columns, `(N,3)` coordinates,
  RGB normalization, and invalid one-/two-dimensional tensors.
- `git diff --check`
- Focused review confirmed raw Tensor handling is isolated before gsplat dict/list normalization and leaves
  existing checkpoint schemas unchanged.

## Bugfix: Dual view cloud visibility (2026-08-18)

- [x] Create a recoverable Git checkpoint before the visibility fix (`b9a4495`).
- [x] Ensure a Dual view pane cannot inherit a hidden source cloud from A-only or B-only single-view state.
- [x] Ensure reused Dual view pane objects are made visible whenever Dual view is activated.
- [x] Run JavaScript/backend checks, browser mode-transition regression coverage, and a focused code review.

2026-08-18 verification completed:

- Active `static/editor.html` script parsed with Node `--check`.
- `py -3.13 -m py_compile app.py` and `git diff --check`.
- In-app browser upload checks using two raw Tensor PT clouds: `B only -> Dual view` retained Cloud A in the
  left pane, and `A only -> Dual view` retained Cloud B in the right pane. Both canvas elements had valid
  dimensions and the browser reported no warnings or errors.
- Focused review confirmed single-view visibility semantics still apply only outside Dual view, while both
  Dual view pane objects are explicitly visible on creation and reuse.

## Current Request: Comparison cloud transform and export (2026-08-18)

- [x] Create a recoverable Git checkpoint before the transform/export implementation (`62518ad`).
- [x] Add independent Cloud A/B selection and TX/TY/TZ plus RX/RY/RZ controls in Comparison mode.
- [x] Apply transforms from immutable source coordinates around each cloud centroid and keep single/Dual view geometry synchronized.
- [x] Export the selected transformed cloud as a binary little-endian PLY with XYZ and RGB.
- [x] Run syntax/backend checks, browser transform/reset/Dual view coverage, PLY byte verification, and focused code review.

2026-08-18 verification completed:

- Active `static/editor.html` script parsed with Node `--check`; `py -3.13 -m py_compile app.py`; `git diff --check`.
- Browser fixture upload loaded two raw Tensor clouds. Cloud A retained `TX=3` and `RZ=90` after selecting Cloud B;
  Cloud B independently retained `TY=2`. Both Dual view canvases had valid dimensions, and reset restored B to zero.
- Browser download produced `comparison_transform_a.transformed.ply`; binary parsing verified two vertices at
  `(4,-1,0)` and `(4,1,0)` with the expected red/green RGB bytes.
- Browser console reported no warnings or errors; the change does not add a backend API or mutate editor state.

## Follow-up: Comparison transform sliders (2026-08-18)

- [x] Add range sliders for Comparison TX/TY/TZ (`-5..5`) and RX/RY/RZ (`-180..180`).
- [x] Synchronize each slider bidirectionally with its numeric input and existing transform/export state.
- [x] Verify slider-to-number, number-to-slider, and independent A/B transform values in the browser.

2026-08-18 verification completed:

- Browser Comparison fixture showed six transform sliders with the expected ranges.
- Dragging TX/RZ set both range and number values to `3`/`90`; switching to Cloud B left those values independent,
  and returning to A restored them. Numeric `TY=-2` input updated its slider, with no browser warnings/errors.

## Current Request: Comparison Evaluate metric report (2026-08-19)

- [x] Create a recoverable Git checkpoint before the Evaluate implementation (`02b2190`).
- [x] Add server-side exact chunked nearest-neighbour metrics for Accuracy, Completeness, Chamfer Distance,
  F-Score, AUC, and PCA-estimated Normal Consistency.
- [x] Apply the current client-side Cloud A/B transforms around each cloud centroid during evaluation,
  with Cloud A fixed as Prediction and Cloud B fixed as Ground Truth.
- [x] Add the Comparison Evaluate panel with six metric checkboxes, defaults for the base four metrics,
  editable `tau`/`tau_max`, validation states, and automatic Markdown download.
- [x] Persist reports under `generated/evaluations/` and add a filename-constrained download endpoint.
- [x] Run backend regression, live-server route, frontend syntax, desktop/mobile browser, console, diff,
  and focused code-review checks.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test client covered identical clouds, directional distances, transforms, strict threshold behavior,
  AUC, planar NC, degenerate NC `N/A`, validation errors, report persistence, download, and Comparison cleanup.
- Live server smoke check confirmed `/api/comparison/evaluate` is not shadowed by the dynamic cloud route;
  the route now constrains `cloud_id` to `a` or `b`.
- Active `static/editor.html` script parsed with Node `new Function`.
- In-app browser verified default checkbox state, disabled/enabled Evaluate state, report summary/download flow,
  `390x844` layout without horizontal overflow, and no console warnings/errors.
- `git diff --check`
- Focused review covered A/B direction, transform parity, bounded distance buffers, PCA edge cases,
  report path validation, and isolation from editor state.

## Current Request: Point-cloud geometric scaling (2026-08-19)

- [x] Create a recoverable Git checkpoint before scaling changes (`a1ad8b5`).
- [x] Add positive scale validation and centroid-based XYZ scaling to Comparison Evaluate,
  Export Current, and Export All; preserve default `scale=1` compatibility.
- [x] Add editor Scale controls with immutable-source preview, centroid-preserving Pivot motion,
  and export request propagation.
- [x] Add independent Comparison A/B Scale controls, transform/report serialization, and Dual-view
  geometry synchronization.
- [x] Run backend regressions, JavaScript syntax checks, desktop/mobile browser checks, console inspection,
  diff validation, and focused code review.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test-client/in-memory regression covered centroid math, default and invalid scales, Comparison
  Evaluate metrics, Export Current, and background Export All outputs.
- Active `static/editor.html` script parsed with Node `--check`.
- In-app browser verified editor and Comparison Scale controls, bidirectional input sync, independent A/B
  values, two Dual-view canvases, mobile `390x844` no-overflow layout, editor-only control hiding, and no
  warning/error console entries.
- `git diff --check`
- Focused review covered scale order, immutable source positions, export parameter capture, report compatibility,
  Dual-pane geometry synchronization, and Comparison/editor state isolation.

## Current Request: Expand local export paths (2026-08-19)

- [x] Resolve `~`, environment variables, and relative paths before writing point-cloud exports.
- [x] Apply the resolved path to both current-frame (`.pt`) and all-frame export endpoints.
- [x] Run compilation, Flask export-path regression checks, frontend syntax/diff checks, and a focused code review.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test-client regression with a temporary simulated home directory confirmed
  `~/Desktop/delete` writes `delete.pt` and all-frame exports use the expanded directory.
- Active `static/editor.html` inline scripts parsed with Node `new Function`.
- `git diff --check`
- Focused review confirmed both public path-bearing export routes resolve user paths before
  directory creation or background worker writes, while extension handling remains unchanged.

## Current Request: Separate Part removal from point deletion (2026-08-19)

- [x] Create a recoverable Git checkpoint before changing Part deletion semantics (`085c784`).
- [x] Preserve the existing non-destructive Part removal operation, with unambiguous UI wording.
- [x] Add an explicit destructive static-vertex deletion operation that compacts point-cloud data
  and remaps every remaining Part's vertex indices.
- [x] Add focused API regression coverage for both operations, export/re-upload behavior, and
  4DGS validation; run syntax, diff, and focused code-review checks.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- Active `static/editor.html` script parsed with Node `--check`.
- Flask test-client regression confirmed non-destructive removal preserves source vertices,
  destructive deletion compacts arrays and remaps surviving Part indices, exported/re-uploaded
  point counts exclude deleted vertices, and 4DGS vertex deletion is rejected.
- `git diff --check`
- Focused review covered shared-array compaction, Part index remapping, empty-workspace state,
  4DGS isolation, confirmation wording, and stale frontend element references.

## Current Request: Expand Scale control range (2026-08-19)

- [x] Raise the editor and Comparison Scale controls' maximum value from `10` to `20`.
- [x] Verify frontend parsing, bounds consistency, and the resulting diff.

2026-08-19 verification completed:

- Inline `static/editor.html` JavaScript parsed successfully with Node.
- PowerShell assertions confirmed editor and Comparison range/number controls and both input clamps use `20`.
- Confirmed no old Scale-specific `10` bound remains; unrelated Total frames bound is unchanged.
- `git diff --check`
- Focused review confirmed the editor and Comparison controls remain synchronized, while the backend API
  validation remains broader (`0 < scale <= 100`) and therefore accepts the new UI maximum.

## Current Request: Default to single-frame export (2026-08-19)

- [x] Change the editor/backend default timeline length to one frame and allow `num_frames=1`.
- [x] Make single-frame batch export treat `~/Desktop/new` as `~/Desktop/new.pt`.
- [x] Run backend export regression, frontend syntax checks, diff validation, and focused code review.

2026-08-19 verification completed:

- `py -3.13 -m py_compile app.py`
- Flask test-client regression with a temporary simulated home directory confirmed the default state is one
  frame, `num_frames=0` is rejected, `~/Desktop/new` writes exactly `new.pt`, and explicit two-frame exports
  still write `frame_0000.pt` and `frame_0001.pt` under the requested directory.
- Active `static/editor.html` inline JavaScript parsed successfully with Node; the editor settings and timeline
  default to one frame, and the export dialog explains the single-file versus multi-frame path behavior.
- `git diff --check`
- Focused review confirmed path expansion occurs before directory creation, single-file exports create only the
  parent directory, multi-frame exports preserve the existing background worker/progress contract, and the legacy
  embedded fallback no longer advertises a stale 30-frame client default.
- [x] Add a visible Back to Editor button inside the Comparison panel.
- [x] Reuse the existing `exitComparison()` cleanup and editor refresh flow.
- [x] Run frontend syntax, Python compile, HTTP smoke, and diff checks.

2026-08-20 verification completed: Node frontend syntax check, `py -3.13 -m py_compile app.py`, HTTP 200 smoke
 check confirmed the updated editor contains the Comparison panel and return button, and `git diff --check` passed.

## Follow-up: Move Comparison return button to top toolbar (2026-08-20)

- [x] Move the return button from the Comparison sidebar to the top toolbar.
- [x] Show it only while Comparison mode is active and keep the existing exit flow.
- [x] Re-run syntax and diff checks.

## Current Request: Expand grid range (2026-08-20)

- [x] Expand the main editor, Comparison, and legacy fallback grids from 20 to 100 units.
- [x] Preserve the original 1-unit grid spacing by matching the division count to the expanded size.
- [x] Run frontend/backend syntax checks and review the focused diff.

## Current Request: Infinite performant grid (2026-08-20)

- [x] Replace finite `GridHelper` geometry with a shader-based procedural grid plane.
- [x] Keep grid rendering bounded to one plane and move it in large camera-target increments.
- [x] Run frontend/backend syntax checks, HTTP smoke, and focused code review.

## Follow-up: Preserve uniform grid cell size (2026-08-20)

- [x] Remove the visually larger 10-unit major grid lines.
- [x] Keep every visible grid line at the original 1-unit spacing and thickness.
- [x] Re-run syntax, browser rendering, and focused diff checks.

## Current Request: Grid depth priority and underside visibility (2026-08-20)

- [x] Make the procedural grid render double-sided so it remains visible when viewed from below.
- [x] Give the grid an explicit low render order and keep coordinate axes above it with a high render order.
- [x] Run frontend/backend syntax checks, browser smoke coverage, diff validation, and focused code review.

2026-08-20 verification completed:

- `py -3.13 -m py_compile app.py`
- Active `static/editor.html` inline JavaScript parsed successfully with Node `--check`.
- Browser smoke check loaded the editor and Comparison viewport, rotated the camera below the grid,
  confirmed the grid remained visible and axes stayed readable, and recorded no console warnings/errors.
- `git diff --check`
- Focused review confirmed transparent grid and axis materials share a render queue, making the explicit
  `renderOrder` values effective; the legacy embedded fallback uses the same double-sided grid behavior.

## Current Request: NPY point-cloud support (2026-08-31)

- [x] Create a recoverable Git checkpoint before the implementation changes (`45fe61d`).
- [x] Add canonical `.npy` parsing for numeric `(N, >=3)` arrays with optional RGB columns.
- [x] Enable `.npy` for initial upload, append upload, Comparison, and server-side frame-directory import.
- [x] Update active and legacy file pickers plus repository documentation.
- [x] Run parser/API/frontend syntax checks, `git diff --check`, and a focused code review before marking this complete.

2026-08-31 verification completed:

- `D:\Develop\Python\CPython\Python313\python.exe -m py_compile app.py`
- In-memory NumPy/Flask regression covered `(N, 3)`, `(N, >=6)`, RGB normalization, identity quaternion defaults,
  initial upload, append upload, Comparison binary payloads, `.pt`/`.npy` directory frames, and invalid shapes.
- Node inline-script parsing confirmed both active editor script blocks are valid JavaScript.
- Live server smoke check returned HTTP 200 for `/` and confirmed the served active page advertises `.npy`.
- `git diff --check`
- Focused review covered extension routing, pickle-disabled NumPy loading, optional RGB fallback behavior, legacy
  multipart 4DGS import, mixed `.pt`/`.npy` frame directories, and preservation of existing `.ply`/`.pt` paths.
