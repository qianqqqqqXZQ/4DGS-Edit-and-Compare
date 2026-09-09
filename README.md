# Part-Level 4DGS Editor

[English](#english) | [中文](#chinese)

<a id="english"></a>

## English

Part-Level 4DGS Editor is a browser-based workspace for inspecting, editing, aligning, and evaluating point clouds and 4D Gaussian Splatting (4DGS) data. A Flask backend manages parsing, state, transforms, evaluation, and export; a local Three.js/WebGL frontend provides the interactive viewport.

The application is intended for reconstruction and LiDAR-alignment workflows where individual scene components need to be selected, repositioned, animated, compared with a reference cloud, and exported in a reusable format.

> Runtime note: the active workspace is kept in server memory. Restarting the Flask process clears the current session. A 4DGS directory must be readable by the server process (and must be mounted into a Docker container when applicable).

### Features

- **Point-cloud import:** Load one or more <code>.ply</code>, <code>.pt</code>, or <code>.npy</code> point clouds. Append additional files to an existing static workspace.
- **Part editing:** Rectangle-select static vertices, create Parts, rename or recolor them, assign vertices, set a pivot or centroid, and apply translation and ZYX rotation.
- **4DGS sequences:** Import a server-side directory of filename-sorted <code>.pt</code>/<code>.npy</code> frames as an animated Part, with optional looping.
- **Keyframed animation:** Set per-Part keyframes, scrub or play the timeline, and interpolate with Linear or Catmull-Rom curves. New workspaces start with one frame.
- **Comparison workspace:** Keep Cloud A (Prediction) and Cloud B (Ground Truth) isolated from the editor. Inspect A only, B only, Both, or synchronized Dual view, with optional linked cameras and a resizable desktop panel.
- **Alignment controls:** Apply independent centroid-based scale, ZYX rotation, and translation to either comparison cloud. Center-align the selected cloud to the other cloud's current centroid.
- **Evaluation:** Compute Accuracy, Completeness, L1 Chamfer Distance, F-Score, AUC, and optional Normal Consistency with exact SciPy <code>cKDTree</code> nearest-neighbour queries.
- **Exports:** Download the current editor frame as a Gaussian <code>.pt</code>, download all editor frames as a ZIP, or export a transformed comparison cloud as <code>.ply</code>, <code>.pt</code>, or <code>.npy</code>.

### Supported input data

| Format | Accepted representation | Interpretation |
| --- | --- | --- |
| <code>.ply</code> | Binary or ASCII PLY with a <code>vertex</code> element | <code>x/y/z</code> are positions. Optional RGB, quaternion, scale, opacity, and spherical-harmonic fields are read when present. |
| <code>.npy</code> | Numeric two-dimensional array shaped <code>(N, >=3)</code> | Columns <code>0..2</code> are XYZ; columns <code>3..5</code>, when present, are RGB and are normalized from either <code>[0, 1]</code> or <code>[0, 255]</code>. Later columns are ignored. |
| <code>.pt</code> checkpoint | Flat or nested gsplat-style dictionary | Common fields include <code>means</code>/<code>xyz</code>, <code>quats</code>, <code>scales</code>, <code>opacities</code>, <code>sh0</code>/<code>features_dc</code>, and <code>shN</code>/<code>features_rest</code>. A nested <code>splats</code> dictionary is supported. |
| Raw <code>.pt</code> tensor | Two-dimensional PyTorch tensor shaped <code>(N, >=3)</code> | Columns <code>0..2</code> are XYZ; columns <code>3..5</code>, when present, are interpreted as RGB. |
| 4DGS directory | A directory containing <code>.pt</code> and/or <code>.npy</code> files | Files are sorted by filename and loaded as source frames. Frames can be looped or clamped to the last source frame. |

When explicit RGB is unavailable, spherical-harmonic DC coefficients are used to derive a display/export fallback. Comparison rendering additionally falls back to neutral gray when neither explicit RGB nor usable SH DC data is available.

### Typical workflow

#### Edit a static or 4DGS scene

1. Start the server and open the editor in a WebGL-capable browser.
2. Select **Upload** to replace the static workspace, or **Add Files** to append point clouds. Each uploaded file becomes an editable Part.
3. Switch from **Orbit** to **Select**, drag a rectangle around static vertices, and choose **Create Part**.
4. Select a Part to edit its name, color, pivot, translation, rotation, point size, or global editor scale.
5. Set keyframes on the timeline, choose the total frame count and interpolation method, then scrub or play the result.
6. Use **Export Current** for one transformed Gaussian frame or **Export All** for a ZIP containing every timeline frame.

Removing a static Part with **Remove Part** only unassigns its vertices. **Delete Part + Points** permanently removes that static Part and its vertices; this action cannot be undone. Vertex deletion is not available for a 4DGS Part.

#### Compare two clouds

1. Open **Comparison** and choose exactly two files. Cloud A is always treated as the Prediction and Cloud B as the Ground Truth.
2. Load the pair, then choose **A only**, **B only**, **Both**, or **Dual view**. Dual view can link camera position, orientation, zoom, and orbit target.
3. Select Cloud A or Cloud B, adjust scale, rotation, and translation, or use **Center align** to match the current centroids.
4. Select metrics and thresholds (<code>tau</code> and <code>tau_max</code>), then choose **Evaluate**. The generated bilingual Markdown report is downloaded by the browser and stored under <code>generated/evaluations/</code>.
5. Choose an export format and use **Export selected** to download the transformed cloud. An optional filename is sanitized and receives the selected extension.

### Comparison evaluation

Cloud A is the prediction point set <code>P</code>; Cloud B is the ground-truth point set <code>G</code>. The submitted transforms are applied before metric calculation. Distances use the source scene's coordinate unit; the application does not infer metres, millimetres, or another physical unit.

| Metric | Definition | Direction |
| --- | --- | --- |
| Accuracy (Acc.) | Mean nearest-neighbour distance <code>mean d(P, G)</code> | Lower is better |
| Completeness (Comp.) | Mean nearest-neighbour distance <code>mean d(G, P)</code> | Lower is better |
| Chamfer Distance (CD-L1) | <code>Accuracy + Completeness</code> | Lower is better |
| F-Score | F1 score from Precision and Recall at threshold <code>tau</code> | Higher is better |
| AUC | Normalized integral of the F-Score curve over 100 thresholds from <code>0</code> to <code>tau_max</code> | Higher is better |
| Normal Consistency (NC) | Mean absolute dot product of matched PCA normals; uses same-cloud <code>k=16</code> neighbours | Higher is better; <code>N/A</code> for insufficient or degenerate neighbourhoods |

Nearest-neighbour and normal-estimation queries use exact Euclidean <code>scipy.spatial.cKDTree</code> searches. The API response and Markdown report include the query engine and evaluation runtime.

### Export behavior

#### Editor exports

- **Current frame:** <code>POST /api/export_current/download</code> returns a browser attachment named from the source file and frame number.
- **All frames:** <code>POST /api/export/download</code> returns a ZIP containing <code>frame_0000.pt</code>, <code>frame_0001.pt</code>, and so on.
- Both browser-download routes accept <code>color_mode: "original"</code> or <code>"edited"</code> and the positive global editor <code>scale</code>.
- Gaussian <code>.pt</code> exports preserve positions, quaternions, scales, opacities, SH DC/rest coefficients, SH degree, and selected RGB data when those attributes exist.
- The original-color mode prefers source RGB, then SH-derived color, then a neutral fallback. Edited mode uses the selected Part color for assigned static vertices and keeps the source fallback for unassigned points.

Path-based server exports remain available for scripts and integrations:

- <code>POST /api/export_current</code> writes one <code>.pt</code> file to the requested <code>output_path</code>.
- <code>POST /api/export</code> writes one <code>.pt</code> file when the workspace has one frame, or a directory of <code>frame_XXXX.pt</code> files for multiple frames. <code>GET /api/export/status</code> reports progress.

#### Comparison exports

<code>POST /api/comparison/export</code> applies the selected cloud's centroid-based scale, ZYX rotation, and translation, then returns an attachment:

- <code>.ply</code>: binary little-endian XYZ <code>float32</code> plus RGB <code>uint8</code>.
- <code>.npy</code>: <code>float32</code> array shaped <code>(N, 6)</code> with XYZ followed by RGB in <code>[0, 1]</code>.
- <code>.pt</code>: raw <code>torch.float32</code> tensor shaped <code>(N, 6)</code> with the same XYZ/RGB columns.

Comparison <code>.pt</code> and <code>.npy</code> files are generic point-cloud exports; they intentionally do not preserve Gaussian quaternions, scales, opacity, or spherical-harmonic attributes.

### API overview

The browser uses JSON and compact binary endpoints. Binary responses use little-endian values and <code>Content-Type: application/octet-stream</code>.

| Area | Endpoints | Purpose |
| --- | --- | --- |
| UI and state | <code>GET /</code>, <code>GET /api/state</code> | Serve the active editor and return workspace metadata. |
| Frames | <code>GET /api/pointcloud</code>, <code>GET /api/frame/&lt;frame&gt;</code>, <code>GET /api/frame_transforms/&lt;frame&gt;</code> | Read source geometry, frame geometry, and keyframed transforms. |
| Upload | <code>POST /api/upload</code>, <code>POST /api/upload_append</code> | Upload one or more static <code>.ply</code>/<code>.pt</code>/<code>.npy</code> files as multipart form data (<code>file</code>). |
| 4DGS | <code>POST /api/upload_4dgs</code> | Load a server-readable frame directory from JSON <code>{ "dir_path": "...", "loop": true/false }</code>. |
| Parts | <code>GET/POST /api/parts</code>, <code>PUT/DELETE /api/parts/&lt;pid&gt;</code>, <code>POST /api/parts/&lt;pid&gt;/assign</code>, <code>DELETE /api/parts/&lt;pid&gt;/vertices</code>, <code>GET /api/parts/&lt;pid&gt;/centroid</code> | Create, edit, assign, remove, or inspect Parts. |
| Keyframes | <code>GET/POST /api/keyframes/&lt;pid&gt;</code>, <code>DELETE /api/keyframes/&lt;pid&gt;/&lt;frame&gt;</code> | Manage per-Part keyframes. |
| Settings | <code>GET/PUT /api/settings</code> | Set timeline frame count and interpolation method. |
| Comparison | <code>POST/DELETE /api/comparison</code>, <code>GET /api/comparison/a</code>, <code>GET /api/comparison/b</code> | Create/clear the isolated comparison session and read each cloud. The upload requires exactly two files under <code>files</code>. |
| Comparison tools | <code>POST /api/comparison/evaluate</code>, <code>POST /api/comparison/export</code>, <code>GET /api/comparison/evaluations/&lt;filename&gt;</code> | Evaluate selected metrics, export a transformed cloud, and download a generated report. |
| Downloads | <code>POST /api/export_current/download</code>, <code>POST /api/export/download</code> | Return browser-friendly current-frame and all-frame downloads without a server path. |

The older compatibility routes (<code>/api/create-part</code>, <code>/api/part/&lt;pid&gt;</code>, <code>/api/keyframes</code>, <code>/api/settings</code>, <code>/api/import-4dgs</code>, <code>/api/export/current</code>, <code>/api/export/all</code>, and <code>/api/download/...</code>) are retained in <code>app.py</code> for existing clients.

For comparison transform JSON, <code>tx</code>, <code>ty</code>, and <code>tz</code> are translations, <code>scale</code> is positive, and <code>rx</code>, <code>ry</code>, and <code>rz</code> are ZYX Euler angles in degrees. Part keyframe values are stored by the backend in radians; the active UI converts its degree controls to that representation.

### Project structure

~~~text
.
├── app.py                         # Flask server, parsers, state, API, evaluation, export
├── static/
│   ├── editor.html                # Active Three.js/WebGL editor UI
│   ├── three.min.js               # Local Three.js runtime (r128)
│   └── OrbitControls.js           # Local orbit-camera controls
├── tests/
│   ├── test_comparison_evaluation.py
│   └── test_export_downloads.py
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Python 3.11 container image
├── generated/                     # Runtime exports and evaluation reports (Git-ignored)
└── project-work/                  # Plans and project reference notes
~~~

<code>app.py</code> also contains a legacy embedded HTML fallback. When <code>static/editor.html</code> is present, the root route serves that active page.

### Requirements

- Python 3.10 or newer (the Docker image uses Python 3.11).
- A WebGL-capable desktop or mobile browser.
- CPU-compatible PyTorch is installed by <code>requirements.txt</code>; CUDA is not required for parsing, evaluation, or export.
- On Linux, the published PyTorch wheels target mainstream 64-bit glibc distributions.

### Quick start

#### Windows PowerShell

~~~powershell
git clone https://github.com/qianqqqqqXZQ/4DGS-Edit-and-Compare.git
cd 4DGS-Edit-and-Compare
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
~~~

#### macOS or Linux

~~~bash
git clone https://github.com/qianqqqqqXZQ/4DGS-Edit-and-Compare.git
cd 4DGS-Edit-and-Compare
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
~~~

Open [http://localhost:5011](http://localhost:5011). The server listens on <code>0.0.0.0:5011</code>, so another device on the same network can use <code>http://&lt;host-ip&gt;:5011</code> after the host firewall allows TCP port <code>5011</code>.

#### Docker

~~~bash
docker build -t part-level-4dgs-editor .
docker run --rm -p 5011:5011 part-level-4dgs-editor
~~~

To import a 4DGS directory in Docker, mount the host directory and enter the container path in the **4DGS Dir** dialog:

~~~bash
docker run --rm -p 5011:5011 \
  -v /absolute/path/to/frames:/data/frames \
  part-level-4dgs-editor
~~~

### Development and verification

Run these commands from the repository root after installing <code>requirements.txt</code>:

~~~bash
python -m py_compile app.py
python -m unittest discover -s tests -p "test_*.py"
git diff --check
~~~

The test suite uses Flask's test client and in-memory fixtures to cover comparison evaluation, transform handling, and browser-download export responses. Frontend changes should also be checked by opening the active page in a desktop and narrow/mobile viewport and inspecting the browser console.

<a id="chinese"></a>

## 中文

Part-Level 4DGS Editor 是一个基于浏览器的点云与 4D Gaussian Splatting（4DGS）编辑、对齐和评估工具。Flask 后端负责文件解析、状态管理、变换、评估和导出；本地 Three.js/WebGL 前端提供交互式三维视口。

项目面向三维重建和 LiDAR 对齐场景：可以把静态点划分为独立 Part，调整位姿并制作关键帧动画，再与参考点云进行 A/B 对比、指标评估和结果导出。

> 运行说明：当前工作区保存在 Flask 进程内存中，重启服务会清空当前会话。4DGS 目录必须能被服务端进程读取；使用 Docker 时需要先把主机目录挂载到容器内。

### 已实现功能

- 支持上传一个或多个 <code>.ply</code>、<code>.pt</code>、<code>.npy</code> 点云，并向现有静态工作区追加文件。
- 支持框选静态顶点、创建/重命名/改色/删除 Part、重新分配顶点、设置枢轴点或质心，以及平移和 ZYX 旋转。
- 支持从服务端目录导入按文件名排序的 <code>.pt</code>/<code>.npy</code> 4DGS 帧序列，并选择循环播放。
- 支持 Part 关键帧、时间轴拖动/播放，以及 Linear 和 Catmull-Rom 插值；新工作区默认只有 1 帧。
- 支持独立的 Comparison 工作区：Cloud A 为 Prediction，Cloud B 为 Ground Truth，可使用 A only、B only、Both 或 Dual view，并可联动相机。
- 支持对任意比较云进行以质心为中心的缩放、ZYX 旋转、平移和 Center align 对齐。
- 支持 Accuracy、Completeness、Chamfer Distance、F-Score、AUC 和可选 Normal Consistency 评估，使用精确的 SciPy <code>cKDTree</code> 查询。
- 支持浏览器下载当前 <code>.pt</code>、全部帧 ZIP，以及比较云的 <code>.ply</code>、<code>.pt</code>、<code>.npy</code> 导出。

### 输入格式

- **PLY：** 读取 <code>x/y/z</code>，并在存在时读取 RGB、四元数、缩放、opacity 和球谐系数。
- **NPY：** 必须是 <code>(N, >=3)</code> 的二维数值数组；第 <code>0..2</code> 列是 XYZ，第 <code>3..5</code> 列可选为 RGB，后续列会忽略。
- **PT：** 支持 gsplat 风格的扁平/嵌套字典（包括 <code>splats</code>），也支持形状为 <code>(N, >=3)</code> 的原始 PyTorch Tensor；前 3 列是 XYZ，接下来的 3 列可作为 RGB。
- **4DGS 目录：** 读取目录内的 <code>.pt</code> 和 <code>.npy</code> 文件，按文件名排序作为帧；可以循环，也可以在最后一帧保持不变。

没有显式 RGB 时，会尝试使用球谐 DC 系数生成颜色；Comparison 在两者都不可用时使用中性灰色。导入数据的数值坐标单位会原样保留，程序不会自动判断米、毫米等物理单位。

### 基本操作流程

1. 启动服务并在支持 WebGL 的浏览器中打开页面。
2. 使用 **Upload** 替换静态工作区，或使用 **Add Files** 追加点云。
3. 切换到 **Select**，框选静态点并点击 **Create Part**。
4. 选中 Part 后编辑名称、颜色、枢轴、平移、旋转、点大小和全局缩放。
5. 在时间轴上设置关键帧，调整总帧数和插值方式，然后拖动或播放预览。
6. 使用 **Export Current** 下载当前高斯帧，或使用 **Export All** 下载包含全部帧的 ZIP。

**Remove Part** 只会取消静态点的 Part 归属，点仍保留在工作区；**Delete Part + Points** 会永久删除该静态 Part 及其顶点，且无法撤销。4DGS Part 不支持顶点删除。

### Comparison、评估与导出

进入 **Comparison** 后，必须选择两个文件：A 始终表示 Prediction，B 始终表示 Ground Truth。加载后可切换单云、叠加或 Dual view，分别调整 A/B 的缩放、旋转和平移，或者使用 **Center align** 对齐当前质心。

评估支持：

- Accuracy：<code>mean d(P, G)</code>，越低越好；
- Completeness：<code>mean d(G, P)</code>，越低越好；
- Chamfer Distance：Accuracy 与 Completeness 之和；
- F-Score：给定 <code>tau</code> 阈值下 Precision 与 Recall 的 F1；
- AUC：<code>0..tau_max</code> 范围内 100 个阈值的归一化 F-Score 积分；
- Normal Consistency：匹配点 PCA 法线的绝对内积均值，邻域不足或退化时返回 <code>N/A</code>。

最近邻和法线估计都使用精确欧氏距离 <code>scipy.spatial.cKDTree</code>。评估会生成中英双语 Markdown 报告，保存到 <code>generated/evaluations/</code> 并由浏览器下载。

Comparison 导出格式如下：<code>.ply</code> 为二进制小端 XYZ <code>float32</code> + RGB <code>uint8</code>；<code>.npy</code> 为 <code>(N, 6)</code> 的 <code>float32</code> 数组；<code>.pt</code> 为相同列布局的原始 <code>torch.float32</code> Tensor。后两者是通用点云格式，不保留高斯四元数、缩放、opacity 或球谐属性。

### 运行与测试

Windows PowerShell：

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
~~~

macOS/Linux：

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
~~~

打开 <code>http://localhost:5011</code>。验证命令：

~~~bash
python -m py_compile app.py
python -m unittest discover -s tests -p "test_*.py"
git diff --check
~~~

项目目录、API、导出路径和二进制数据布局的完整说明请以上方 English 部分为准。运行时导出和评估报告位于 <code>generated/</code>（已加入 Git 忽略），计划与项目备忘位于 <code>project-work/</code>。
