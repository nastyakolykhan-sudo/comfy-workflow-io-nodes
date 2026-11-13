"""Workflow IO Image Reframe.

Image Reframe as a workflow input: in the ComfyUI editor it works like Image
Reframe (drag the frame in the viewport to crop, rotate, pad, pick the padding
colour, feather), but takes its picture from a connected ``image`` or
``video`` instead of an upload. In a deployed workflow its frame widgets are
the API parameter: the app shows its own crop tool on the image or video that
reaches this node and sends the frame back in ``center_x``, ``center_y``,
``frame_width``, ``frame_height``, ``rotation``, ``padding_color`` and
``feathering`` (``aspect_ratio`` locks the tool's proportions).

With a video the whole clip is reframed with one frame; the editor shows one
frame at a time with a timeline and a play button.
"""

from .common import CATEGORY_INPUT, editor_run, meta_widgets
from .inputs import display_widget

MAX_RESOLUTION = 16384
ASPECT_RATIO_CHOICES = ["free", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]
PADDING_COLOR_CHOICES = ["grey", "black", "white", "green"]
CROP_DATA_TYPE = "CROP_DATA"  # same type as Image Reframe, for Image Reframe Composite
# How the deployed app shows the crop: the frame over the whole original, or only what's inside it.
REFRAME_DISPLAY_OPTIONS = ["crop in image", "crop only"]

# The frame widgets, in order: what the deployed app's crop tool sets.
FRAME_FIELDS = ("center_x", "center_y", "frame_width", "frame_height", "rotation",
                "aspect_ratio", "padding_color", "feathering")


class WorkflowIOImageReframe:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        meta = meta_widgets(default_required=False)
        return {
            "required": {
                "param_name": meta["param_name"],
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
                **{k: v for k, v in meta.items() if k != "param_name"},
                "display": display_widget(
                    REFRAME_DISPLAY_OPTIONS,
                    "How the deployed app shows the crop: 'crop in image' = the frame over the whole original "
                    "image, 'crop only' = just the cropped result, without the parts cut off.",
                ),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "The image to reframe (a single image or a batch; the whole "
                                               "batch uses the same frame). Connect this or video."}),
                "video": ("VIDEO", {"tooltip": "The video to reframe; every frame uses the same frame. "
                                               "Connect this or image."}),
                "mask": ("MASK", {"tooltip": "Cropped with the same frame and combined into the mask output"}),
            },
            "hidden": {
                "node_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", CROP_DATA_TYPE, "VIDEO")
    RETURN_NAMES = ("original_image", "cropped_image", "mask", "crop_data", "cropped_video")
    OUTPUT_TOOLTIPS = (
        "The source, uncropped: the image, or every frame of the video",
        "The frame, with the padding filled with padding_color (every frame, for a video)",
        "1 in the padded area; over the image, the cropped input mask (or 0), faded in by feathering",
        "The frame's geometry, for Image Reframe Composite",
        "The reframed video, with the source's audio and frame rate (from an image: 24 fps, no audio)",
    )
    DESCRIPTION = (
        "Reframes the connected image or video: drag the frame in the viewport to crop, turn the image "
        "behind it with rotation, or push the frame past the edges to pad the canvas. In a deployed "
        "workflow the app shows its own crop tool for this frame. Run the workflow once to see the "
        "picture in the viewport; with a video, use the timeline to pick a frame or play it."
    )

    def run(self, param_name, center_x, center_y, frame_width, frame_height, rotation, aspect_ratio,
            padding_color, feathering, image=None, video=None, mask=None, node_id=None, extra_pnginfo=None,
            **_meta):
        # aspect_ratio only constrains dragging (editor and app).
        from . import _reframe as R

        if image is None and video is None:
            raise ValueError(f"Workflow IO Image Reframe '{param_name}': connect an image or a video.")
        if image is not None and video is not None:
            raise ValueError(f"Workflow IO Image Reframe '{param_name}': connect either an image or a video, "
                             f"not both.")

        audio = None
        if video is not None:
            components = video.get_components()
            source, audio, frame_rate = components.images, components.audio, components.frame_rate
        else:
            source, frame_rate = image, R.IMAGE_VIDEO_FPS

        batch, src_h, src_w, _ = source.shape
        cx, cy, w, h = R.frame_geometry(src_w, src_h, center_x, center_y, frame_width, frame_height,
                                        even=video is not None)
        src_mask = None if mask is None else R.normalize_mask(mask, batch, src_h, src_w).to(source.device)
        out_image, out_mask = R.reframe(source, src_mask, cx, cy, w, h, rotation, padding_color, feathering)
        out_video = R.to_video(out_image, frame_rate, audio)

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
            elif video is not None:
                ui["reframe_video"] = [R.save_video_preview(source, frame_rate, node_id)]
                ui["reframe_frames"] = [batch, float(frame_rate)]
            else:
                ui["reframe_preview"] = [R.save_image_preview(source, node_id)]
        except Exception as exc:  # the viewport preview must never fail a run
            print(f"[Workflow IO Image Reframe] preview skipped: {exc}")

        return {"ui": ui, "result": (source, out_image, out_mask, crop_data, out_video)}
