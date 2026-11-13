"""Workflow IO Image/Video Reframe and its Composite.

Image Reframe as a workflow editing node: in the ComfyUI editor it works like
Image Reframe (drag the frame in the viewport to crop, rotate, pad, pick the
padding colour, feather) on the connected image or video. In a deployed
workflow the app shows its own crop tool on whatever reaches this node and sends
the frame back in ``center_x``, ``center_y``, ``frame_width``, ``frame_height``,
``rotation``, ``padding_color`` and ``feathering`` (``aspect_ratio`` locks the
tool's proportions, ``display`` says how the app shows the crop).

``mode`` picks image or video. The sockets keep fixed names (``source`` in;
``original``, ``cropped`` out; the Composite's ``frame``, ``original`` in and
``result`` out) and accept either type, so links survive saving and loading; the
editor labels and types them for the chosen mode: image -> ``image`` in,
``original_image`` / ``cropped_image`` out; video -> ``video`` in,
``original_video`` / ``cropped_video`` out (plus ``mask`` and ``crop_data``).

With a video the whole clip is reframed with one frame; the editor shows one
frame at a time with a timeline and a play button.

The Composite pastes back across that frame: the original onto a processed
frame (outpainting) or the processed crop back into the original, for images
or videos.
"""

from .common import ANY_TYPE, CATEGORY_INPUT, editor_run
from .inputs import display_widget

MAX_RESOLUTION = 16384
MEDIA_MODES = ["image", "video"]
ASPECT_RATIO_CHOICES = ["free", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]
PADDING_COLOR_CHOICES = ["grey", "black", "white", "green"]
CROP_DATA_TYPE = "CROP_DATA"  # same type as Image Reframe, for either Composite
# How the deployed app shows the crop: the frame over the whole original, or only what's inside it.
REFRAME_DISPLAY_OPTIONS = ["crop in image", "crop only"]
PASTE_OPTIONS = ["original onto frame", "crop onto original"]

MODE_WIDGET = (MEDIA_MODES, {"default": "image",
                             "tooltip": "Image or video: sets which input and outputs the node shows."})


def _name(node):
    return node.__class__.__name__.replace("WorkflowIO", "Workflow IO ").replace("ImageVideo", "Image/Video ")


def _is_video(value):
    return hasattr(value, "get_components")


def _check_source(node, value, is_video, name):
    if value is None:
        raise ValueError(f"{_name(node)}: {'video' if is_video else 'image'} mode, connect the "
                         f"{'video' if is_video else 'image'} ({name}).")
    if is_video != _is_video(value):
        got = "a video" if _is_video(value) else "an image"
        raise ValueError(f"{_name(node)}: mode is {'video' if is_video else 'image'}, but {name} got {got}. "
                         f"Switch mode to {'video' if not is_video else 'image'}.")


def _video_parts(video):
    """(frames, audio, frame_rate) of a VIDEO."""
    components = video.get_components()
    return components.images, components.audio, components.frame_rate


class WorkflowIOImageVideoReframe:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": MODE_WIDGET,
                "center_x": ("FLOAT", {"default": 0.0, "min": -MAX_RESOLUTION, "max": MAX_RESOLUTION, "step": 0.5,
                                       "tooltip": "Frame centre, in source pixels"}),
                "center_y": ("FLOAT", {"default": 0.0, "min": -MAX_RESOLUTION, "max": MAX_RESOLUTION, "step": 0.5,
                                       "tooltip": "Frame centre, in source pixels"}),
                "frame_width": ("INT", {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1,
                                        "tooltip": "Frame width in source pixels; 0 = full image"}),
                "frame_height": ("INT", {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1,
                                         "tooltip": "Frame height in source pixels; 0 = full image"}),
                "rotation": ("FLOAT", {"default": 0.0, "min": -180.0, "max": 180.0, "step": 0.1,
                                       "display": "slider",
                                       "tooltip": "Rotates the image behind the frame, in degrees "
                                                  "(positive = clockwise)"}),
                "aspect_ratio": (ASPECT_RATIO_CHOICES, {"default": "free",
                                                        "tooltip": "Locks the frame's proportions while dragging "
                                                                   "(here and in the deployed app's crop tool)"}),
                "padding_color": (PADDING_COLOR_CHOICES, {"default": "grey",
                                                          "tooltip": "Fill for the frame area outside the image"}),
                "feathering": ("INT", {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1,
                                       "tooltip": "Fades the mask from the padding into the image over this many "
                                                  "pixels, along the image edges that border padding"}),
                "display": display_widget(
                    REFRAME_DISPLAY_OPTIONS,
                    "How the deployed app shows the crop: 'crop in image' = the frame over the whole original "
                    "image, 'crop only' = just the cropped result, without the parts cut off.",
                ),
            },
            "optional": {
                # IMAGE in image mode, VIDEO in video mode (the editor labels it image / video).
                "source": (ANY_TYPE, {"tooltip": "Image mode: the image to reframe (a batch uses one frame for all). "
                                                 "Video mode: the video; every frame uses the same frame."}),
                "mask": ("MASK", {"tooltip": "Cropped with the same frame and combined into the mask output"}),
            },
            "hidden": {
                "node_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    # original and cropped are IMAGE in image mode and VIDEO in video mode (the editor
    # labels them original_image / cropped_image or original_video / cropped_video).
    RETURN_TYPES = (ANY_TYPE, ANY_TYPE, "MASK", CROP_DATA_TYPE)
    RETURN_NAMES = ("original", "cropped", "mask", "crop_data")
    OUTPUT_TOOLTIPS = (
        "The source, uncropped: the image (image mode) or the video, passed through (video mode)",
        "The frame, with the padding filled with padding_color: an image, or a video with the source's audio "
        "and frame rate",
        "1 in the padded area; over the image, the cropped input mask (or 0), faded in by feathering",
        "The frame's geometry, for Workflow IO Image/Video Reframe Composite (or Image Reframe Composite)",
    )
    DESCRIPTION = (
        "Reframes the connected image or video (pick it with mode): drag the frame in the viewport to crop, "
        "turn the image behind it with rotation, or push the frame past the edges to pad the canvas. In a "
        "deployed workflow the app shows its own crop tool for this frame. Run the workflow once to see the "
        "picture in the viewport; with a video, use the timeline to pick a frame or play it."
    )

    def run(self, mode, center_x, center_y, frame_width, frame_height, rotation, aspect_ratio, padding_color,
            feathering, display="crop in image", source=None, mask=None, node_id=None, extra_pnginfo=None):
        # aspect_ratio only constrains dragging (editor and app); display only tells the app how to show it.
        from . import _reframe as R

        is_video = mode == "video"
        _check_source(self, source, is_video, "source")
        image, video = (None, source) if is_video else (source, None)

        audio = None
        if is_video:
            source, audio, frame_rate = _video_parts(video)
        else:
            source, frame_rate = image, R.IMAGE_VIDEO_FPS

        batch, src_h, src_w, _ = source.shape
        cx, cy, w, h = R.frame_geometry(src_w, src_h, center_x, center_y, frame_width, frame_height, even=is_video)
        src_mask = None if mask is None else R.normalize_mask(mask, batch, src_h, src_w).to(source.device)
        out_image, out_mask = R.reframe(source, src_mask, cx, cy, w, h, rotation, padding_color, feathering)

        crop_data = {
            "source_width": src_w,
            "source_height": src_h,
            "center_x": float(cx),
            "center_y": float(cy),
            "width": int(w),
            "height": int(h),
            "angle": float(rotation),
        }

        ui = {"reframe_source_size": [src_w, src_h]}
        try:
            if not editor_run(extra_pnginfo):
                pass  # API run: no editor preview
            elif is_video:
                ui["reframe_video"] = [R.save_video_preview(source, frame_rate, node_id)]
                ui["reframe_frames"] = [batch, float(frame_rate)]
            else:
                ui["reframe_preview"] = [R.save_image_preview(source, node_id)]
        except Exception as exc:  # the viewport preview must never fail a run
            print(f"[{_name(self)}] preview skipped: {exc}")

        if is_video:
            result = (video, R.to_video(out_image, frame_rate, audio), out_mask, crop_data)
        else:
            result = (source, out_image, out_mask, crop_data)
        return {"ui": ui, "result": result}


class WorkflowIOImageVideoReframeComposite:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": MODE_WIDGET,
                "paste": (PASTE_OPTIONS, {
                    "default": PASTE_OPTIONS[0],
                    "tooltip": "'original onto frame': puts the original back onto the processed frame "
                               "(outpainting); output in frame space. 'crop onto original': puts the processed "
                               "crop back into the original, undoing the rotation; output in original space."}),
                "feather": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 1,
                                    "tooltip": "Soft edge width in output pixels: inside the frame border when "
                                               "pasting the crop, inside the original's edges that border padding "
                                               "when pasting the original"}),
                "resize_source": ("BOOLEAN", {"default": False,
                                              "tooltip": "The source is what's pasted (the original or the crop). "
                                                         "On: it is scaled to the other's resolution. Off: it keeps "
                                                         "its pixels and the other is scaled to match."}),
            },
            "optional": {
                # IMAGE in image mode, VIDEO in video mode (the editor labels them frame_image /
                # original_image or frame_video / original_video).
                "frame": (ANY_TYPE, {"tooltip": "The processed frame: the edited crop or the outpainted result, any "
                                                "resolution (an image, or a video in video mode)."}),
                "original": (ANY_TYPE, {"tooltip": "The original, from the Reframe node's original output."}),
                "mask": ("MASK", {"tooltip": "Limits the paste to this region (in frame space, any resolution)"}),
                "crop_data": (CROP_DATA_TYPE, {"tooltip": "From the Reframe node (required)"}),
            },
        }

    # IMAGE in image mode, VIDEO in video mode (the editor labels it image / video).
    RETURN_TYPES = (ANY_TYPE,)
    RETURN_NAMES = ("result",)
    OUTPUT_TOOLTIPS = ("The composite: an image, or a video with the original's audio and frame rate",)
    DESCRIPTION = (
        "Pastes back across a Workflow IO Image/Video Reframe frame, for images or videos (pick with mode): the "
        "original onto a processed or outpainted frame, or the processed crop back into the original (undoing "
        "crop, padding and rotation), with optional feathering. With videos, frames are matched by time."
    )

    def run(self, mode, paste, feather, resize_source, frame=None, original=None, mask=None, crop_data=None):
        from . import _reframe as R

        if crop_data is None:
            raise ValueError(f"{_name(self)}: connect crop_data from the Reframe node.")
        is_video = mode == "video"
        _check_source(self, frame, is_video, "frame")
        _check_source(self, original, is_video, "original")
        if is_video:
            frames, frame_audio, frame_fps = _video_parts(frame)
            source, audio, fps = _video_parts(original)
            frames = R.time_align(frames, source.shape[0], frame_fps, fps)
            out = R.composite(frames, source, crop_data, paste, feather, resize_source, mask)
            return (R.to_video(out, fps, audio if audio else frame_audio),)
        return (R.composite(frame, original, crop_data, paste, feather, resize_source, mask),)
