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

Every input node shares this metadata block: `param_name` (the API key),
`required`, `description`, `example`, `advanced`, `group`, `order`.

Int, Float and Bool inputs also carry `display`, after the metadata block: how
the deployed app shows the input to users. It is optional: API workflows saved
before it existed leave it out and get the default.

| Input | `display` options (first = default) |
|-------|-------------------------------------|
| Int, Float | `number` = a number box they type in or step up/down; `slider` = a slider they drag between `min` and `max` (give a slider a real range) |
| Bool | `on/off` = two buttons, On and Off, they pick between; `toggle` = a switch they flip |

Enum inputs carry `mode` in the same place (also optional): `single` (default) = users pick
one option; `multi-select` = users pick any number. In multi-select `value` is
the chosen options separated by commas (`Plant, Lamp`; empty = nothing picked),
the app sends its picks the same way, and the node outputs them joined with
", " (for text and prompt inputs; a multi-select can't drive a single-choice
dropdown).

API exports without the key (workflows saved before it existed) mean the
default. It sits last so that saved UI workflows, which store widget values by
position, still load unchanged.

### Editing nodes (`Workflow IO/Inputs`)

Media passes **through** these nodes; in a deployed workflow the app shows its
crop, trim or point tool on whatever reaches them and sends the node's fields
back. They have **no metadata block** (no `param_name`, `required`,
`description`, `example`, `advanced`, `group`, `order`): the app finds them by
class. In the editor each one shows the media after a first run.

| Node | In | Out | App tool |
|------|----|-----|----------|
| Workflow IO Image/Video Reframe | `source` (image or video), `mask` | `original`, `cropped`, `mask`, `crop_data` | crop / pad / rotate |
| Workflow IO Image/Video Reframe Composite | `frame`, `original`, `mask`, `crop_data` | `result` | (none: pastes back) |
| Workflow IO Video Trim | `video` | `video`, `keyframe`, `start_frame`, `end_frame`, `duration_trimmed`, `duration_total`, `keyframe_index`, `trim_data` | trim (+ keyframe) |
| Workflow IO Video Trim Composite | `trimmed_video`, `original_video`, `trim_data` | `video` | (none: puts the part back) |
| Workflow IO Point Selector | `image` | `image`, `positive_coords`, `negative_coords` | positive / negative points |

**Image or video (`mode`).** The Reframe and its Composite have `mode` image /
video. Their media sockets keep fixed names (`source`, `original`, `cropped`,
`frame`, `result`) and accept either type, so links survive saving and loading;
the editor labels and types them for the mode:

| mode | Reframe in → out | Composite in → out |
|------|------------------|--------------------|
| image | image → original_image, cropped_image | frame_image, original_image → image |
| video | video → original_video, cropped_video | frame_video, original_video → video |

A mismatch (a video into image mode) stops the run with a clear message.

#### Workflow IO Image/Video Reframe

Image Reframe (ComfyUI-MaskAspectCrop) for images and videos. Any image or
video that should be **cropped, padded or rotated** in a deployed workflow goes
through this node.

- **In the editor** it works like Image Reframe without the upload: run once
  and the viewport shows the picture. Drag the frame to crop, push it past the
  edges to pad, turn the image with `rotation`, pick `padding_color`, set
  `feathering`. In video mode the viewport shows one frame at a time, with a
  timeline to scrub and a play button (the frame can be dragged while it
  plays); the whole clip is reframed with the one frame.
- **Frame fields** (the app's crop tool sets them, in source pixels):
  `center_x`, `center_y`, `frame_width`, `frame_height` (0 = full image),
  `rotation` (degrees, clockwise), `padding_color` (grey/black/white/green),
  `feathering` (px). `aspect_ratio` (free/16:9/4:3/1:1/3:4/9:16/21:9) only
  locks the frame's proportions while dragging, in the editor and in the app.
  `display`: how the app shows the crop, `crop in image` (default: the frame
  over the whole original) or `crop only` (just the cropped result, without
  the parts cut off).
- **Outputs:** `original` (the image, or the video passed through), `cropped`
  (an image, or a video with the source's audio and frame rate), `mask` (1 in
  the padding, feathered into the image), `crop_data` (the same `CROP_DATA` as
  Image Reframe, so either Composite can paste back).
- In video mode the frame size is rounded down to even numbers (encoders need
  them); the editor shows the rounded size.
- **For the app:** show the crop tool on whatever reaches `source` (usually a
  Workflow IO Image / Video Input upload). The frame is in pixels of the source
  it was drawn on, so start the tool at the full frame for each new upload and
  send the fields back.

```
WorkflowIOImageVideoReframe node "7"  ->  inputs = {
    mode: "video", center_x: 240, center_y: 135, frame_width: 184,
    frame_height: 326, rotation: -6, aspect_ratio: "9:16",
    padding_color: "black", feathering: 0, display: "crop only",
    source: ["4", 0] }
```

#### Workflow IO Image/Video Reframe Composite

Image Reframe Composite for images and videos: `paste` `original onto frame`
(default; puts the original back onto a processed or outpainted frame, output
in frame space) or `crop onto original` (puts the processed crop back into the
original, undoing crop and rotation; output in original space), `feather`
(px), `resize_source`, optional `mask`. `frame` is the processed result,
`original` and `crop_data` come from the Reframe node. In video mode frames are
matched by time (a processed clip at another frame rate or length still lines
up) and the result keeps the original's audio and frame rate.

#### Workflow IO Video Trim

Load Video (Trim + Keyframe) (ComfyUI-VideoTrimmer) for a video passing
through. Any video the person running the workflow should **trim** goes
through this node.

- **In the editor** it works like Load Video (Trim + Keyframe) without the
  upload: run once and the timeline shows the video (thumbnail strip, white
  playhead, yellow trim handles that snap to the other markers, play, arrow
  keys ±1 / shift ±10, space to play). Frame numbers come with their time
  (`Frame 37 · 1.50s`; start, end and keyframe in the readout).
- **`mode`**: `trim` (default) = a start and an end; `trim + keyframe` = also a
  keyframe, which appears as soon as the mode is picked (at the playhead) and
  is dragged on the timeline. In `trim` mode the keyframe is hidden and
  ignored (the keyframe outputs give the start frame). The mode also tells the
  app whether its trim tool shows a keyframe marker.
- **Trim fields** (the app's trim tool sets them): `start_frame` (from 1),
  `end_frame` (inclusive; 0 = the last frame, which the editor also stores
  when the end handle sits on the last frame), `keyframe` (0 = the start
  frame; must lie inside the trim).
- **Outputs:** `video` (trimmed, with its audio), `keyframe` (IMAGE),
  `start_frame`, `end_frame`, `duration_trimmed`, `duration_total` (frames),
  `keyframe_index` (0-based inside the trim), as in Load Video (Trim +
  Keyframe), plus `trim_data` (where the trim sits, for the Trim Composite).
- A video that is a plain file (a Workflow IO Video Input or Load Video
  upload) is trimmed frame-exactly from its timestamps, without decoding;
  anything else (generated in the graph, already trimmed) is decoded and
  sliced.
- **For the app:** show the trim tool on whatever reaches `video`; frame
  numbers are counted in that video, so start at the whole video for each new
  upload.

#### Workflow IO Video Trim Composite

Puts a processed version of the trimmed part back into the original video's
timeline: frames `start_frame`..`end_frame` (from `trim_data`) are replaced,
the rest of the video and its audio stay as they were, and the processed frames
are resized to the original's size. `fit`: `by time` (default; the processed
part plays at its own speed, cut short or its last frame held to fill the slot)
or `stretch` (sped up or slowed down to fill the slot exactly). The original
must be the video that went into the trim node.

#### Workflow IO Point Selector

Positive and negative points on an image passing through. Any image the person
running the workflow should **click points on** (for segmentation) goes
through this node.

- **In the editor** it works like a points editor: run once, then click to add
  a positive point (green), shift-click or right-click for a negative one
  (red), drag to move, right-click a point to delete it, "Clear points" to
  start over.
- **Point fields** (the app's point tool sets them): `positive_points`,
  `negative_points` as JSON `[{"x": 120, "y": 340}, ...]` in pixels of the
  image (empty = none; `[[x, y], ...]` is accepted too). Points outside the
  image are moved onto its edge.
- **Outputs:** `image` (passed through), `positive_coords`,
  `negative_coords`: JSON in KJNodes Points Editor's format, which core SAM3
  Detect (`positive_coords` / `negative_coords`) and SAM2
  (`coordinates_positive` / `coordinates_negative`) read. No points → `[]`.
- **Video segmentation:** pass the keyframe (Video Trim in `trim + keyframe`
  mode) through this node, segment that frame (SAM3 Detect), then track from
  it with AutoMatte: SAM3 Track From Keyframe (ComfyUI-AutoMatte), which takes
  `keyframe_index` and tracks forward and backward with core SAM3. Core SAM3
  Video Track and SAM2's main node always start from the first frame of the
  frames they get. (SeC takes an annotation frame, but its model bundles
  Qwen2.5-3B under a research-only, non-commercial licence.)
- **For the app:** show the point tool on whatever reaches `image`; points
  are in that image's pixels, so start empty for each upload.

**Editor previews.** The editing nodes write their viewport/timeline preview (a
small H.264 copy, a thumbnail strip, a PNG) to ComfyUI's temp folder only when
the run was queued from the editor (which sends the UI workflow along); API
runs skip it.

### Outputs (`Workflow IO/Outputs`)
| Node | Takes | Notes |
|------|-------|-------|
| Workflow IO Image Output | IMAGE | full saver (png/jpg/webp); passthrough IMAGE |
| Workflow IO Video Output | VIDEO | saves via `comfy_api`'s `VideoInput.save_to` (SaveVideo-style, audio preserved); passthrough VIDEO; `codec` (auto/h264/av1/prores, ComfyUI 0.44+) and a wirable `video_format` string (MP4, ProRes, WebM, MKV, auto) that overrides format + codec — ProRes is written as MOV (422 HQ, or 4444 for 4:4:4/alpha sources) |
| Workflow IO 3D Output | FILE_3D (GLB, glTF, FBX, OBJ, STL) | saves in the file's own format via `File3D.save_to` (Save 3D-style), reported under the `3d` UI key; passthrough FILE_3D |
| Workflow IO Text Output | STRING | saves a UTF-8 `.txt`, reported under the `files` UI key (deployments return it as a `file` output) and as `text`; shows the text on the node after a run; passthrough STRING; `action` / `fills` make it a step the app runs on its own (below) |

Output nodes are `OUTPUT_NODE` and pass their media through, so they can sit
mid-graph without dead-ending a branch.

> **MVP scope note:** Image and video input/output are fully implemented, both
> preserving audio end-to-end via the native VIDEO type. Text output is in;
> Audio/File output nodes are planned fast-follows.

#### Actions: a step the app runs before the real run (Suggest prompt)

A Workflow IO Text Output with `action` set (a button label, e.g. `Suggest
prompt`) and `fills` (the `param_name` of an input, e.g. `Prompt`) is a step the
app runs on its own. Example: a video edit whose prompt an LLM can write from the
clip and the reference. The user presses **Suggest prompt**, the written prompt
appears in the Prompt field, they read it, change it if they like, and press
Generate: the real run uses the field as it is, so what they see is what runs.

How the app runs it:

1. **The action** (button pressed): send the workflow trimmed to that Text Output
   and every node that feeds it. ComfyUI runs every output node it is given, and
   deployments drop ComfyUI's `partial_execution_targets`, so trimming is how
   only the suggestion branch runs (no render). Send values only for the inputs
   left in the trimmed workflow; enable the button once those are filled.
2. **The result**: the job returns one `file` output, `<output_name>.txt` (UTF-8);
   its content goes into the input named by `fills`.
3. **The real run**: send the workflow without its action outputs, with the
   input as the user left it. Nodes that only fed the action don't run.

[`tools/action_graph.py`](tools/action_graph.py) does both trims and lists each
action's inputs (`python tools/action_graph.py workflow_api.json [--write]`).
With `action` empty, the text is simply returned with the normal run.

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

WorkflowIOTextOutput node "9" with action  ->  api_config.actions["Suggest prompt"] = {
    node_id: "9", fills: "prompt", inputs: ["video", "reference_image"] }
    # left out of output_nodes and of the normal run's workflow
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
