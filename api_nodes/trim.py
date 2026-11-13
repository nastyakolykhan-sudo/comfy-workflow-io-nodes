"""Workflow IO Video Trim.

Load Video (Trim + Keyframe) as a workflow input: in the ComfyUI editor it works
like that node (a timeline with trim handles, a playhead, play, and an optional
keyframe), but trims the connected ``video`` instead of an upload. In a deployed
workflow its trim widgets are the API parameter: the app shows its own trim tool
on the video that reaches this node and sends back ``start_frame``,
``end_frame`` and ``keyframe``.

Frames are counted from 1 and the range is inclusive; ``end_frame`` 0 = the last
frame, ``keyframe`` 0 = none (the start frame is used).
"""

from fractions import Fraction

from .common import CATEGORY_INPUT, editor_run, meta_widgets

MAX_FRAMES = 10_000_000
# "trim": start and end only (the keyframe outputs give the start frame);
# "trim + keyframe": also a keyframe. Also tells the deployed app whether its
# trim tool shows a keyframe marker.
TRIM_MODES = ["trim", "trim + keyframe"]


class WorkflowIOVideoTrim:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        meta = meta_widgets(default_required=False)
        return {
            "required": {
                "param_name": meta["param_name"],
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
                                                "video; it must lie inside the trim. 0 = no keyframe set "
                                                "(the start frame is used). Ignored in 'trim' mode."}),
                **{k: v for k, v in meta.items() if k != "param_name"},
            },
            "hidden": {
                "node_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("VIDEO", "IMAGE", "INT", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("video", "keyframe", "start_frame", "end_frame", "duration_trimmed", "duration_total",
                    "keyframe_index")
    OUTPUT_TOOLTIPS = (
        "The trimmed video, frames start_frame..end_frame, with its audio.",
        "The frame under the keyframe marker (the start frame in 'trim' mode or when no keyframe is set).",
        "First frame kept, counted from 1 in the whole video.",
        "Last frame kept, counted from 1 in the whole video.",
        "Number of frames in the trimmed video.",
        "Number of frames in the whole video.",
        "Position of the keyframe inside the trimmed video, counted from 0 "
        "(keyframe - start_frame). Plugs into a frame index of nodes that take the trimmed frames.",
    )
    DESCRIPTION = (
        "Trims the connected video to a frame range on a timeline and picks a keyframe. In a deployed "
        "workflow the app shows its own trim tool for it. Run the workflow once to load the video into "
        "the timeline. Frame numbers start at 1; durations are in frames."
    )

    def run(self, param_name, video, start_frame, end_frame, keyframe, mode="trim", node_id=None,
            extra_pnginfo=None, **_meta):
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
                raise ValueError(f"Workflow IO Video Trim '{param_name}': the video has no frames.")

        start, end, key = V.clamp_range(total, start_frame, end_frame, keyframe)
        if not start <= key <= end:
            raise ValueError(f"Workflow IO Video Trim '{param_name}': keyframe {key} is outside the trimmed range "
                             f"{start}-{end}. Move the keyframe inside the trim, or the trim around it.")

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
                raise RuntimeError(f"Workflow IO Video Trim '{param_name}': could not decode frame {key}.")
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
                    "trim_info": [{"frames": total, "fps": float(fps), "width": int(width), "height": int(height),
                                   "strip_count": strip_count, "preview_frames": written}],
                }
            except Exception as exc:  # the editor's preview must never fail a run
                print(f"[Workflow IO Video Trim] preview skipped: {exc}")

        result = (trimmed, key_image.contiguous(), start, end, end - start + 1, total, key - start)
        return {"ui": ui, "result": result}
