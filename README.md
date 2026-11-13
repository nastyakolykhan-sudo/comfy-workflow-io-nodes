# comfy-workflow-io-nodes

Custom ComfyUI nodes that let a workflow author declare its **API contract
inside the graph** — inputs and outputs — instead of hand-mapping them in a
deploy UI. When the workflow is exported as API JSON, these nodes carry all
the contract metadata as widget values, and a workflow parser reads them to
auto-build the entire `api_config`.

## The idea

- **Input nodes** are passthrough: they hold a `value` and output it, so you
  wire their output into whatever downstream node needs it. The API runner
  overrides `value` per call. The injection target is always this node's own
  `value` field — stable and unambiguous, so it never points into a third-party
  node the user might swap out.
- **Output nodes** mark what gets returned to the caller and control the
  client-facing filename — authored in the graph (wire the `filename` input for
  fully dynamic names, e.g. from an intermediate caption or seed).

## Nodes

### Inputs (`Workflow IO/Inputs`)
| Node | Output | Notes |
|------|--------|-------|
| Workflow IO Text Input | STRING | single/multi-line |
| Workflow IO Int Input | INT | min/max/step; `display` number/slider |
| Workflow IO Float Input | FLOAT | min/max/step; `display` number/slider |
| Workflow IO Bool Input | BOOLEAN | `display` on/off / toggle |
| Workflow IO Enum Input | STRING | `options` → API enum allowlist; `mode` single/multi-select (see below) |
| Workflow IO Seed Input | INT | `randomize_if_omitted` |
| Workflow IO Image Input | IMAGE, MASK | LoadImage-style; reads the file the runner writes to the input dir |
| Workflow IO Video Input | VIDEO | LoadVideo-style; reads the file the runner writes to the input dir, decoding deferred to whatever consumes the VIDEO |
| Workflow IO Image Reframe | IMAGE (original, cropped), MASK, CROP_DATA, VIDEO | crop / pad / rotate an `image` or `video` passing through; see below |
| Workflow IO Video Trim | VIDEO, IMAGE (keyframe), INT ×5 | trim a `video` passing through to a frame range, pick a keyframe; see below |
| Workflow IO Point Selector | IMAGE, STRING ×2 | positive / negative points on an `image` passing through, for SAM-style segmenters; see below |

Every input node shares this metadata block: `param_name` (the API key),
`required`, `description`, `example`, `advanced`, `group`, `order`.

Int, Float, Bool and Image Reframe inputs also carry `display`, after the
metadata block: how the deployed app shows the input to users.

| Input | `display` options (first = default) |
|-------|-------------------------------------|
| Int, Float | `number` = a number box they type in or step up/down; `slider` = a slider they drag between `min` and `max` (give a slider a real range) |
| Bool | `on/off` = two buttons, On and Off, they pick between; `toggle` = a switch they flip |
| Image Reframe | `crop in image` = the frame drawn over the whole original image; `crop only` = just the cropped result, without the parts cut off |

Enum inputs carry `mode` in the same place: `single` (default) = users pick
one option; `multi-select` = users pick any number. In multi-select `value` is
the chosen options separated by commas (`Plant, Lamp`; empty = nothing picked),
the app sends its picks the same way, and the node outputs them joined with
", " (for text and prompt inputs; a multi-select can't drive a single-choice
dropdown).

API exports without the key (workflows saved before it existed) mean the
default. It sits last so that saved UI workflows, which store widget values by
position, still load unchanged.

### Workflow IO Image Reframe

Image Reframe (ComfyUI-MaskAspectCrop) as a workflow input. Any image or
video that should be **cropped, padded or rotated** in a deployed workflow
goes through this node; the deployed app shows its crop tool for it.

- **In the editor** it works like Image Reframe without the upload: connect an
  `image` or a `video` (one, not both; optional `mask`), run once, and the
  viewport shows the picture. Drag the frame to crop, push it past the edges
  to pad, turn the image with `rotation`, pick `padding_color`, set
  `feathering`. With a video the viewport shows one frame at a time, with a
  timeline to scrub and a play button (the frame can be dragged while it
  plays); the whole clip is reframed with the one frame.
- **Frame fields** (the API parameter; the app's crop tool sets them, in
  source pixels): `center_x`, `center_y`, `frame_width`, `frame_height`
  (0 = full image), `rotation` (degrees, clockwise), `padding_color`
  (grey/black/white/green), `feathering` (px). `aspect_ratio`
  (free/16:9/4:3/1:1/3:4/9:16/21:9) only locks the frame's proportions while
  dragging, in the editor and in the app's crop tool. Plus the shared
  metadata block (`required` defaults to false), then `display`: how the app
  shows the crop, `crop in image` (default: the frame over the whole
  original) or `crop only` (just the cropped result).
- **Outputs:** `original_image` (the image, or every video frame),
  `cropped_image`, `mask` (1 in the padding, feathered into the image),
  `crop_data` (the same `CROP_DATA` as Image Reframe, so Image Reframe
  Composite can paste results back) and `cropped_video` (the source's audio
  and frame rate; from an image, 24 fps without audio).
- With a video the frame size is rounded down to even numbers (encoders need
  them); the editor shows the rounded size.
- **For the app:** show the crop tool on whatever reaches this node's `image`
  or `video` input (usually a Workflow IO Image / Video Input upload). The
  frame is in pixels of the source it was drawn on, so start the tool at the
  full frame for each new upload and send the fields back.

```
WorkflowIOImageReframe node "7"  ->  inputs = {
    param_name: "Crop", center_x: 240, center_y: 135, frame_width: 184,
    frame_height: 326, rotation: -6, aspect_ratio: "9:16",
    padding_color: "black", feathering: 0, required: false, ...,
    video: ["4", 0] }
```

### Workflow IO Video Trim

Load Video (Trim + Keyframe) (ComfyUI-VideoTrimmer) as a workflow input. Any
video the person running the workflow should **trim** goes through this node;
the deployed app shows its trim tool for it.

- **In the editor** it works like Load Video (Trim + Keyframe) without the
  upload: connect a `video`, run once, and the timeline shows it (thumbnail
  strip, white playhead, yellow trim handles that snap to the other markers,
  a cyan keyframe, play, arrow keys ±1 / shift ±10, space to play).
- **`mode`**: `trim` (default) = a start and an end; `trim + keyframe` = also
  a keyframe. It also tells the app whether its trim tool shows a keyframe
  marker. In `trim` mode the editor hides the keyframe controls and the node
  ignores `keyframe` (the keyframe outputs give the start frame).
- **Trim fields** (the API parameter; the app's trim tool sets them):
  `start_frame` (from 1), `end_frame` (inclusive; 0 = the last frame, which the
  editor also stores when the end handle sits on the last frame), `keyframe`
  (0 = none, the start frame is used; must lie inside the trim). Plus the
  shared metadata block (`required` defaults to false).
- **Outputs:** `video` (trimmed, with its audio), `keyframe` (IMAGE),
  `start_frame`, `end_frame`, `duration_trimmed`, `duration_total` (frames)
  and `keyframe_index` (0-based inside the trim), as in Load Video (Trim +
  Keyframe).
- A video that is a plain file (a Workflow IO Video Input or Load Video
  upload) is trimmed frame-exactly from its timestamps, without decoding;
  anything else (generated in the graph, already trimmed) is decoded and
  sliced.
- **For the app:** show the trim tool on whatever reaches this node's `video`
  input; frame numbers are counted in that video, so start at the whole video
  for each new upload.

### Workflow IO Point Selector

Positive and negative points as a workflow input. Any image the person running
the workflow should **click points on** (for segmentation) goes through this
node; the deployed app shows its point tool for it.

- **In the editor** it works like a points editor: connect an `image`, run
  once, then click to add a positive point (green), shift-click or right-click
  for a negative one (red), drag to move, right-click a point to delete it,
  "Clear points" to start over.
- **Point fields** (the API parameter; the app's point tool sets them):
  `positive_points`, `negative_points` as JSON `[{"x": 120, "y": 340}, ...]`
  in pixels of the image (empty = none; `[[x, y], ...]` is accepted too).
  Points outside the image are moved onto its edge. Plus the shared metadata
  block (`required` defaults to false).
- **Outputs:** `image` (passed through), `positive_coords`,
  `negative_coords`: JSON in KJNodes Points Editor's format, which core SAM3
  Detect (`positive_coords` / `negative_coords`), SAM2 and SeC
  (`positive_points` / `coordinates_positive` ...) read. No points → `[]`.
- **Video segmentation:** pass the keyframe (Workflow IO Video Trim in
  `trim + keyframe` mode) through this node, segment that frame, and use
  `keyframe_index` as the tracker's annotation frame (SeC
  `annotation_frame_idx`; for SAM3 Video Track, start the frames at the
  keyframe and give it SAM3 Detect's mask as `initial_mask`).
- **For the app:** show the point tool on whatever reaches this node's `image`
  input; points are in that image's pixels, so start empty for each upload.

**Editor previews.** All three nodes write their viewport/timeline preview (a small
H.264 copy, a thumbnail strip, a PNG) to ComfyUI's temp folder only when the run was
queued from the editor (which sends the UI workflow along); API runs skip it.

### Outputs (`Workflow IO/Outputs`)
| Node | Takes | Notes |
|------|-------|-------|
| Workflow IO Image Output | IMAGE | full saver (png/jpg/webp); passthrough IMAGE |
| Workflow IO Video Output | VIDEO | saves via `comfy_api`'s `VideoInput.save_to` (SaveVideo-style, audio preserved); passthrough VIDEO; `codec` (auto/h264/av1/prores, ComfyUI 0.44+) and a wirable `video_format` string (MP4, ProRes, WebM, MKV, auto) that overrides format + codec — ProRes is written as MOV (422 HQ, or 4444 for 4:4:4/alpha sources) |
| Workflow IO 3D Output | FILE_3D (GLB, glTF, FBX, OBJ, STL) | saves in the file's own format via `File3D.save_to` (Save 3D-style), reported under the `3d` UI key; passthrough FILE_3D |

Output nodes are `OUTPUT_NODE` and pass their media through, so they can sit
mid-graph without dead-ending a branch.

> **MVP scope note:** Image and video input/output are fully implemented, both
> preserving audio end-to-end via the native VIDEO type. Text/Audio/File
> output nodes are planned fast-follows.

## Exported-JSON → api_config contract

Each API node serializes its widgets into the API JSON `inputs`. The
parser maps:

```
WorkflowIOTextInput node "2"  ->  api_config.mappings["prompt"] = {
    node_id: "2", field: "value", type: "string", required: true,
    default: {enabled: true, value: "a photograph of a cat"},
    tooltip: "<description>", advanced_setting: false }

WorkflowIOFloatInput node "5"  ->  api_config.mappings["strength"] = {
    node_id: "5", field: "value", type: "float", ...,
    min: 0, max: 1, step: 0.05, display: "slider" }   # "number" when absent

WorkflowIOImageOutput node "8"  ->  api_config.output_nodes = ["8", ...]
```

Because `output_nodes` is emitted as an allowlist (not a rename map), the runner
returns each output with the exact filename the node saved — no server-side
renaming. See [`examples/sample_api_workflow.json`](examples/sample_api_workflow.json)
for the full exported shape the parser consumes.

## Install

The node folder just needs to live in a ComfyUI `custom_nodes/` directory.

- **Local / interactive dev:** clone into `ComfyUI/custom_nodes/` and restart.
- **v3 runner** (`modal/v3/comfyui.py`): add this repo's URL to the
  `CUSTOM_NODES` list (cloned at image build).
- **v2 editor + runner** (workspace-based): the folder must be present
  in each workspace's `custom_nodes/`. Because these are platform nodes that must
  exist everywhere, prefer baking them into the base image + a startup symlink
  into the active workspace rather than per-workspace installs. **Deploy to both
  the editor (`comfyui-instance-v2`) and the runner (`comfyui-api-runner-v2`)** —
  installing only one leaves the other failing at cold start.

No third-party pip dependencies (uses ComfyUI's existing torch/numpy/Pillow).

## Dev

```bash
# contract smoke test (no ComfyUI needed — heavy imports are lazy inside run())
python3 -c "from api_nodes import NODE_CLASS_MAPPINGS; print(len(NODE_CLASS_MAPPINGS))"
```
