"""Workflow IO Point Selector.

Positive and negative points on an image, as a workflow input. In the ComfyUI
editor it works like a points editor: run once, click on the image to add
points, and wire the coordinates into a segmentation node (core SAM3 Detect,
SAM2, SeC and others that read KJNodes Points Editor's format). In a deployed
workflow its point fields are the API parameter: the app shows its own point
tool on the image that reaches this node and sends the points back.

For video segmentation, pass the keyframe (Workflow IO Video Trim in
"trim + keyframe" mode) through this node and use ``keyframe_index`` as the
segmenter's annotation frame.

Points are pixel coordinates in the image passing through, as JSON:
``[{"x": 120, "y": 340}, ...]``.
"""

import json

from .common import CATEGORY_INPUT, editor_run

POINTS_TOOLTIP = ('{kind} points in pixels of the image, as JSON: [{{"x": 120, "y": 340}}, ...]. '
                  'Set by clicking in the viewport (and by the deployed app\'s point tool). Empty = none.')


def parse_points(text, kind, width=None, height=None):
    """[{"x": int, "y": int}, ...] from JSON; also accepts [[x, y], ...]. Points
    outside the image are moved onto its edge."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"Workflow IO Point Selector: {kind} points are not valid JSON ({exc}). "
                         f'Expected [{{"x": 120, "y": 340}}, ...].') from None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError(f"Workflow IO Point Selector: {kind} points must be a JSON list.")
    points = []
    for item in raw:
        if isinstance(item, dict) and "x" in item and "y" in item:
            x, y = item["x"], item["y"]
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x, y = item[0], item[1]
        else:
            raise ValueError(f"Workflow IO Point Selector: can't read {kind} point {item!r}; "
                             f'use {{"x": 120, "y": 340}}.')
        x, y = int(round(float(x))), int(round(float(y)))
        if width:
            x = min(max(x, 0), width - 1)
        if height:
            y = min(max(y, 0), height - 1)
        points.append({"x": x, "y": y})
    return points


class WorkflowIOPointSelector:
    CATEGORY = CATEGORY_INPUT
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "The image to place points on (for a video: its keyframe). "
                                               "A batch uses the first image."}),
                "positive_points": ("STRING", {"default": "", "tooltip": POINTS_TOOLTIP.format(kind="Positive")}),
                "negative_points": ("STRING", {"default": "", "tooltip": POINTS_TOOLTIP.format(kind="Negative")}),
            },
            "hidden": {
                "node_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "positive_coords", "negative_coords")
    OUTPUT_TOOLTIPS = (
        "The image, passed through unchanged.",
        'Positive points as JSON [{"x": int, "y": int}, ...], for positive_coords / coordinates_positive inputs.',
        'Negative points as JSON [{"x": int, "y": int}, ...], for negative_coords / coordinates_negative inputs.',
    )
    DESCRIPTION = (
        "Positive and negative points on the connected image, for segmentation nodes such as SAM3 Detect, SAM2 "
        "and SeC. Run the workflow once to see the image, then click to add positive points and shift-click "
        "(or right-click) to add negative ones. In a deployed workflow the app shows its own point tool."
    )

    def run(self, image, positive_points, negative_points, node_id=None, extra_pnginfo=None):
        height, width = int(image.shape[1]), int(image.shape[2])
        positive = parse_points(positive_points, "positive", width, height)
        negative = parse_points(negative_points, "negative", width, height)

        ui = {"points_source_size": [width, height]}
        if editor_run(extra_pnginfo):
            try:
                from . import _reframe as R
                ui["points_preview"] = [R.save_image_preview(image, node_id, prefix="wfio_points_preview")]
            except Exception as exc:  # the viewport preview must never fail a run
                print(f"[Workflow IO Point Selector] preview skipped: {exc}")

        return {"ui": ui, "result": (image, json.dumps(positive), json.dumps(negative))}
