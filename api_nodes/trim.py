"""Workflow IO Video Trim and its Composite.

Load Video (Trim + Keyframe) as a workflow editing node: in the ComfyUI editor it
works like that node (a timeline with trim handles, a playhead, play, and in
"trim + keyframe" mode a keyframe), but trims the connected ``video`` instead of
an upload. In a deployed workflow the app shows its own trim tool on the video
that reaches this node and sends back ``start_frame``, ``end_frame`` and
``keyframe``.

Frames are counted from 1 and the range is inclusive; ``end_frame`` 0 = the last
frame, ``keyframe`` 0 = the start frame.

The Composite puts a processed version of the trimmed part back into the
original video's timeline, using the trim node's ``trim_data``.
"""

from fractions import Fraction

from .common import CATEGORY_INPUT, editor_run

MAX_FRAMES = 10_000_000
# "trim": start and end only (the keyframe outputs give the start frame);
# "trim + keyframe": also a keyframe. Also tells the deployed app whether its
# trim tool shows a keyframe marker.
TRIM_MODES = ["trim", "trim + keyframe"]
TRIM_DATA_TYPE = "TRIM_DATA"
FIT_OPTIONS = ["by time", "stretch"]
NAME = "Workflow IO Video Trim"


class WorkflowIOVideoTrim:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO", {"tooltip": "The video to trim."}),
                "mode": (TRIM_MODES, {"default": "trim",
                                      "tooltip": "'trim' = set a start and an end; 'trim + keyframe' = also pick a "
                                                 "keyframe for the keyframe outputs. The deployed app's trim tool "
                                                 "shows the keyframe marker only in 'trim + keyframe'."}),
                "start_frame": ("INT", {"default": 1, "min": 1, "max": MAX_FRAMES,
                                        "tooltip": "First frame kept (1 = first frame of the video)."}),
                "end_frame": ("INT", {"default": 0, "min": 0, "max": MAX_FRAMES,
                                      "tooltip": "Last frame kept, inclusive. 0 = last frame of the video."}),
                "keyframe": ("INT", {"default": 0, "min": 0, "max": MAX_FRAMES,
                                     "tooltip": "Frame sent to the keyframe output, counted from 1 in the whole "
                                                "video; it must lie inside the trim. 0 = the start frame. "
                                                "Ignored in 'trim' mode."}),
            },
            "hidden": {
                "node_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("VIDEO", "IMAGE", "INT", "INT", "INT", "INT", "INT", TRIM_DATA_TYPE)
    RETURN_NAMES = ("video", "keyframe", "start_frame", "end_frame", "duration_trimmed", "duration_total",
                    "keyframe_index", "trim_data")
    OUTPUT_TOOLTIPS = (
        "The trimmed video, frames start_frame..end_frame, with its audio.",
        "The frame under the keyframe marker (the start frame in 'trim' mode).",
        "First frame kept, counted from 1 in the whole video.",
        "Last frame kept, counted from 1 in the whole video.",
        "Number of frames in the trimmed video.",
        "Number of frames in the whole video.",
        "Position of the keyframe inside the trimmed video, counted from 0 "
        "(keyframe - start_frame). Plugs into a frame index of nodes that take the trimmed frames.",
        "Where the trim sits in the original, for Workflow IO Video Trim Composite.",
    )
    DESCRIPTION = (
        "Trims the connected video to a frame range on a timeline and, in 'trim + keyframe' mode, picks a "
        "keyframe. In a deployed workflow the app shows its own trim tool for it. Run the workflow once to "
        "load the video into the timeline. Frame numbers start at 1; durations are in frames."
    )

    def run(self, video, mode, start_frame, end_frame, keyframe, node_id=None, extra_pnginfo=None):
        from . import _video as V

        if mode != "trim + keyframe":
            keyframe = 0  # trim only: the keyframe outputs give the start frame

        path = V.file_source(video)
        components = None
        if path is not None:
            info = V.probe(path)
            total = len(info["pts"])
            fps = info["fps"]
        else:
            components = video.get_components()
            total = int(components.images.shape[0])
            fps = Fraction(components.frame_rate)
            if total == 0:
                raise ValueError(f"{NAME}: the video has no frames.")

        start, end, key = V.clamp_range(total, start_frame, end_frame, keyframe)
        if not start <= key <= end:
            raise ValueError(f"{NAME}: keyframe {key} is outside the trimmed range {start}-{end}. "
                             f"Move the keyframe inside the trim, or the trim around it.")

        if path is not None:
            VideoFromFile = V._video_from_file_cls()
            if start == 1 and end == total:
                trimmed = video
            else:
                start_time, duration = V.window(info, start - 1, end - 1)
                trimmed = VideoFromFile(path, start_time=start_time, duration=duration)
            key_start, key_duration = V.window(info, key - 1, key - 1)
            key_image = VideoFromFile(path, start_time=key_start, duration=key_duration).get_components().images[:1]
            if key_image.shape[0] == 0:
                raise RuntimeError(f"{NAME}: could not decode frame {key}.")
        else:
            from comfy_api.input_impl import VideoFromComponents
            from comfy_api.util import VideoComponents

            if start == 1 and end == total:
                trimmed = video
            else:
                trimmed = VideoFromComponents(VideoComponents(
                    images=components.images[start - 1:end],
                    audio=V.slice_audio(components.audio, fps, start, end),
                    frame_rate=components.frame_rate,
                ))
            key_image = components.images[key - 1:key]

        ui = {}
        if editor_run(extra_pnginfo):
            try:
                width, height = video.get_dimensions()
                size = V.preview_size(width, height)
                frames = V.file_frames(path, size) if path is not None else V.tensor_frames(components.images, size)
                video_ref, strip_ref, strip_count, written = V.write_preview(frames, total, fps, node_id)
                ui = {
                    "trim_video": [video_ref],
                    "trim_strip": [strip_ref] if strip_ref else [],
                    # The frames' own size: a phone clip's rotation tag is applied (get_dimensions
                    # gives the stored size, which file_frames needs before it rotates).
                    "trim_info": [{"frames": total, "fps": float(fps), "width": int(key_image.shape[2]),
                                   "height": int(key_image.shape[1]),
                                   "strip_count": strip_count, "preview_frames": written}],
                }
            except Exception as exc:  # the editor's preview must never fail a run
                print(f"[{NAME}] preview skipped: {exc}")

        trim_data = {"start_frame": start, "end_frame": end, "total_frames": total, "frame_rate": float(fps),
                     "keyframe": key}
        result = (trimmed, key_image.contiguous(), start, end, end - start + 1, total, key - start, trim_data)
        return {"ui": ui, "result": result}


class WorkflowIOVideoTrimComposite:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trimmed_video": ("VIDEO", {"tooltip": "The processed version of the trimmed part."}),
                "original_video": ("VIDEO", {"tooltip": "The whole original video (what went into the trim node)."}),
                "trim_data": (TRIM_DATA_TYPE, {"tooltip": "From Workflow IO Video Trim."}),
                "fit": (FIT_OPTIONS, {
                    "default": FIT_OPTIONS[0],
                    "tooltip": "When the processed part's length or frame rate differs from the trimmed part: "
                               "'by time' = plays it at its own speed (cut short, or its last frame held, to fill "
                               "the slot); 'stretch' = speeds it up or slows it down to fill the slot exactly."}),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    OUTPUT_TOOLTIPS = ("The original video with the trimmed frames replaced, with the original's audio and "
                       "frame rate.",)
    DESCRIPTION = (
        "Puts a processed version of a trimmed part back into the original video's timeline, in place of frames "
        "start_frame..end_frame from Workflow IO Video Trim's trim_data. The rest of the video and its audio stay "
        "as they were; the processed frames are resized to the original's size."
    )

    def run(self, trimmed_video, original_video, trim_data, fit):
        from . import _reframe as R
        from comfy_api.input_impl import VideoFromComponents
        from comfy_api.util import VideoComponents

        name = "Workflow IO Video Trim Composite"
        original = original_video.get_components()
        frames = original.images
        total = int(frames.shape[0])
        if int(trim_data["total_frames"]) != total:
            raise ValueError(f"{name}: the original video has {total} frames, but the trim was made on a video with "
                             f"{trim_data['total_frames']}. Connect the video that went into the trim node.")
        start, end = int(trim_data["start_frame"]), int(trim_data["end_frame"])
        slot = end - start + 1

        part = trimmed_video.get_components()
        seg = part.images
        if seg.shape[0] == 0:
            raise ValueError(f"{name}: the trimmed video has no frames.")
        if fit == "stretch":
            idx = [min(seg.shape[0] - 1, int(i * seg.shape[0] / slot)) for i in range(slot)]
        else:
            seg_fps = float(part.frame_rate or original.frame_rate)
            idx = [min(seg.shape[0] - 1, int(i * seg_fps / float(original.frame_rate) + 1e-6)) for i in range(slot)]
        seg = R._resize(seg[idx, :, :, :3].float(), frames.shape[1], frames.shape[2])

        out = frames.clone()
        out[start - 1:end, :, :, :3] = seg.to(device=out.device, dtype=out.dtype)
        return (VideoFromComponents(VideoComponents(images=out, audio=original.audio,
                                                    frame_rate=original.frame_rate)),)
