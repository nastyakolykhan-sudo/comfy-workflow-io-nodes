"""Reframe geometry for Workflow IO Image Reframe.

Ported from Image Reframe (ComfyUI-MaskAspectCrop) so this pack stays
self-contained: the same frame, rotation, padding and feathering, and the same
``crop_data`` shape, so Image Reframe Composite can paste results back.

Geometry: a w x h frame centred at (cx, cy) in source pixels, with the image
rotated by ``angle`` degrees (positive = clockwise on screen) behind the
upright frame. The frame may extend past the image on any side; that area is
the padding. An output pixel at offset d from the frame centre samples the
source at c + R(-angle) d.

Imported lazily by the node (torch is only needed at run time).
"""

import math
import os
import re
from fractions import Fraction

import torch
import torch.nn.functional as F

PADDING_COLORS = {
    "grey": (0.5, 0.5, 0.5),
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "green": (0.0, 1.0, 0.0),
}
IMAGE_PREVIEW_MAX_SIDE = 1024
VIDEO_PREVIEW_MAX_SIDE = 640
IMAGE_VIDEO_FPS = 24  # frame rate of the video output when the source is an image
CHUNK = 16  # frames resampled at once, to cap peak memory on long videos


def _cos_sin(angle):
    a = math.radians(angle)
    return math.cos(a), math.sin(a)


def _frame_to_source(cx, cy, w, h, angle, out_w, out_h, device):
    """Source coordinates of every pixel of a w x h frame rendered at out_w x out_h."""
    cos_a, sin_a = _cos_sin(angle)
    xs = (torch.arange(out_w, device=device, dtype=torch.float32) + 0.5) * (w / out_w) - w / 2
    ys = (torch.arange(out_h, device=device, dtype=torch.float32) + 0.5) * (h / out_h) - h / 2
    dy, dx = torch.meshgrid(ys, xs, indexing="ij")
    return cx + cos_a * dx + sin_a * dy, cy - sin_a * dx + cos_a * dy


def _source_grid(sx, sy, src_w, src_h):
    return torch.stack((sx / src_w * 2 - 1, sy / src_h * 2 - 1), dim=-1).unsqueeze(0)


def _sample(batch_chw, grid, mode, padding_mode):
    """grid_sample a (B, C, H, W) tensor with one shared grid by folding the
    batch into channels, so the grid never has to be repeated per frame."""
    b, c, h, w = batch_chw.shape
    out = F.grid_sample(
        batch_chw.reshape(1, b * c, h, w), grid,
        mode=mode, padding_mode=padding_mode, align_corners=False,
    )
    return out.reshape(b, c, grid.shape[1], grid.shape[2])


def _match_batch(t, batch_size):
    if t.shape[0] == batch_size:
        return t
    if t.shape[0] == 1:
        return t.expand(batch_size, *t.shape[1:])
    raise ValueError(f"Batch size mismatch: got {t.shape[0]}, expected {batch_size} (or 1).")


def normalize_mask(mask, batch_size, h, w):
    if mask.dim() == 4 and mask.shape[1] == 1:
        mask = mask.squeeze(1)
    elif mask.dim() == 2:
        mask = mask.unsqueeze(0)
    mask = _match_batch(mask.float(), batch_size)
    if mask.shape[1:] != (h, w):
        mask = F.interpolate(mask.unsqueeze(1), size=(h, w), mode="bilinear", align_corners=False).squeeze(1)
    return mask


def frame_geometry(src_w, src_h, center_x, center_y, frame_width, frame_height, even=False):
    """(cx, cy, w, h) of the frame; 0 width or height = the full image.

    ``even`` rounds the size down to even numbers (video encoders need them),
    keeping the top-left corner where it was.
    """
    if frame_width <= 0 or frame_height <= 0:
        cx, cy, w, h = src_w / 2, src_h / 2, int(src_w), int(src_h)
    else:
        cx, cy, w, h = float(center_x), float(center_y), int(frame_width), int(frame_height)
    if even:
        ew, eh = max(2, w - w % 2), max(2, h - h % 2)
        cx, cy, w, h = cx - (w - ew) / 2, cy - (h - eh) / 2, ew, eh
    return cx, cy, w, h


def reframe(source, src_mask, cx, cy, w, h, rotation, padding_color, feathering):
    """Reframe a (B, H, W, C) batch. Returns (image (B, h, w, 3), mask (B, h, w))."""
    batch, src_h, src_w, _ = source.shape
    device = source.device
    color = torch.tensor(PADDING_COLORS[padding_color], device=device, dtype=torch.float32)
    out_image = torch.empty((batch, h, w, 3), device=device, dtype=torch.float32)
    crop_mask = None if src_mask is None else torch.zeros((batch, h, w), device=device)
    x0, y0 = cx - w / 2, cy - h / 2

    if rotation % 360 == 0 and float(x0).is_integer() and float(y0).is_integer():
        # Exact pixel copy: paste the overlapping part onto a filled canvas.
        x0, y0 = int(x0), int(y0)
        out_image[:] = color
        coverage = torch.zeros((h, w), device=device)
        ix0, iy0 = max(0, x0), max(0, y0)
        ix1, iy1 = min(src_w, x0 + w), min(src_h, y0 + h)
        if ix1 > ix0 and iy1 > iy0:
            oy, ox = slice(iy0 - y0, iy1 - y0), slice(ix0 - x0, ix1 - x0)
            for i in range(0, batch, CHUNK):
                out_image[i:i + CHUNK, oy, ox] = source[i:i + CHUNK, iy0:iy1, ix0:ix1, :3].float()
            coverage[oy, ox] = 1
            if src_mask is not None:
                crop_mask[:, oy, ox] = src_mask[:, iy0:iy1, ix0:ix1]
    else:
        sx, sy = _frame_to_source(cx, cy, w, h, rotation, w, h, device)
        grid = _source_grid(sx, sy, src_w, src_h)
        ones = torch.ones((1, 1, src_h, src_w), device=device)
        coverage = _sample(ones, grid, "bilinear", "zeros")[0, 0]
        cov = coverage[None, ..., None]
        for i in range(0, batch, CHUNK):
            # Sample with border padding and blend by coverage, so edges fade
            # into the padding colour instead of a dark fringe.
            part = source[i:i + CHUNK, ..., :3].float().movedim(-1, 1)
            sampled = _sample(part, grid, "bicubic", "border").movedim(1, -1).clamp(0, 1)
            out_image[i:i + CHUNK] = sampled * cov + color * (1 - cov)
            if src_mask is not None:
                crop_mask[i:i + CHUNK] = _sample(src_mask[i:i + CHUNK].unsqueeze(1), grid, "bilinear", "border")[:, 0]

    # Over the image: the cropped input mask, raised by the feathering ramp.
    inner = crop_mask
    if feathering > 0:
        # Same falloff as Pad Image for Outpainting: ((f - d) / f)^2 from the edge
        # pixel to 0 at `feathering` px in, on edges that border padding.
        sx, sy = _frame_to_source(cx, cy, w, h, rotation, w, h, device)
        edges = [(sx, sx < 0), (src_w - sx, sx > src_w), (sy, sy < 0), (src_h - sy, sy > src_h)]
        distance = torch.full_like(sx, float("inf"))
        for dist, beyond in edges:
            if beyond.any():
                distance = torch.minimum(distance, dist + 0.5)
        ramp = ((feathering - distance) / feathering).clamp(0, 1) ** 2
        inner = ramp if inner is None else torch.maximum(inner, ramp)

    # 1 in the padding; over the image, `inner` (or 0).
    if inner is None:
        out_mask = (1 - coverage).expand(batch, h, w).contiguous()
    else:
        out_mask = ((1 - coverage) + coverage * inner).expand(batch, h, w).contiguous()
    return out_image, out_mask


def to_video(images, frame_rate, audio=None):
    """A VIDEO from frames. Odd sizes lose their last row/column (encoders need even)."""
    from comfy_api.input_impl import VideoFromComponents
    from comfy_api.util import VideoComponents

    h, w = images.shape[1], images.shape[2]
    if h % 2 or w % 2:
        images = images[:, :max(2, h - h % 2), :max(2, w - w % 2)]
    return VideoFromComponents(VideoComponents(images=images, audio=audio, frame_rate=Fraction(frame_rate)))


def _temp_name(prefix, node_id, ext):
    import folder_paths

    temp_dir = folder_paths.get_temp_directory()
    os.makedirs(temp_dir, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(node_id or "node"))
    filename = f"{prefix}_{safe}.{ext}"
    return filename, os.path.join(temp_dir, filename)


def _scaled_size(w, h, max_side, even=False):
    s = min(1.0, max_side / max(w, h))
    if even:
        return max(2, round(w * s / 2) * 2), max(2, round(h * s / 2) * 2)
    return max(1, round(w * s)), max(1, round(h * s))


def save_image_preview(source, node_id, prefix="wfio_reframe_preview"):
    """The first image, downscaled, for the editor's viewport."""
    from PIL import Image

    frame = (source[0, :, :, :3].float().clamp(0, 1) * 255).byte().cpu().numpy()
    pil = Image.fromarray(frame)
    pil.thumbnail((IMAGE_PREVIEW_MAX_SIDE, IMAGE_PREVIEW_MAX_SIDE))
    filename, path = _temp_name(prefix, node_id, "png")
    pil.save(path, compress_level=1)
    return {"filename": filename, "subfolder": "", "type": "temp"}


def save_video_preview(frames, frame_rate, node_id):
    """A small H.264 copy of the source video for the editor's viewport and timeline."""
    from comfy_api.input_impl import VideoFromComponents
    from comfy_api.util import VideoCodec, VideoComponents, VideoContainer

    src_h, src_w = frames.shape[1], frames.shape[2]
    pw, ph = _scaled_size(src_w, src_h, VIDEO_PREVIEW_MAX_SIDE, even=True)
    parts = []
    for i in range(0, frames.shape[0], CHUNK):
        part = frames[i:i + CHUNK, ..., :3].float().movedim(-1, 1)
        parts.append(F.interpolate(part, size=(ph, pw), mode="bilinear", align_corners=False,
                                   antialias=True).movedim(1, -1).clamp(0, 1).cpu())
    small = torch.cat(parts)
    filename, path = _temp_name("wfio_reframe_preview", node_id, "mp4")
    VideoFromComponents(VideoComponents(images=small, frame_rate=Fraction(frame_rate))).save_to(
        path, format=VideoContainer.MP4, codec=VideoCodec.H264)
    return {"filename": filename, "subfolder": "", "type": "temp"}
