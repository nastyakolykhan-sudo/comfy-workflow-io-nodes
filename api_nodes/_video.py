"""Video helpers for Workflow IO Video Trim (imported lazily, at run time).

Frame-exact trimming ported from Load Video (Trim + Keyframe) (ComfyUI-VideoTrimmer):
a trim window becomes the (start_time, duration) that ComfyUI's own VideoFromFile
uses, chosen from the stream's real packet timestamps, so the decode keeps exactly
frames start..end without decoding anything here. Videos that aren't a plain file
(generated in the graph, already trimmed or cropped) are decoded and sliced instead.

Also writes the editor's preview: a small H.264 copy of the whole source plus a
thumbnail strip, both in ComfyUI's temp folder.
"""

import os
import re
from collections import OrderedDict
from fractions import Fraction

import av
from PIL import Image

# start_time sits a tenth of a tick after the start frame's pts; the window ends
# on the next frame's pts.
PTS_NUDGE = 0.1
PREVIEW_MAX_SIDE = 640
STRIP_TILES = 40
STRIP_TILE_H = 96

_probe_cache = OrderedDict()


def _video_from_file_cls():
    try:
        from comfy_api.latest import InputImpl
        return InputImpl.VideoFromFile
    except ImportError:  # older ComfyUI
        from comfy_api.input_impl import VideoFromFile
        return VideoFromFile


def file_source(video):
    """Path of the file behind a VIDEO when it can be trimmed by timestamps:
    a VideoFromFile on a file on disk, not already trimmed or cropped. Else None."""
    cls = _video_from_file_cls()
    if not isinstance(video, cls):
        return None
    src = video.get_stream_source()
    if not isinstance(src, str) or not os.path.isfile(src):
        return None
    window = getattr(video, "get_active_trim_window", None)
    if window is not None:
        if tuple(float(v) for v in window()) != (0.0, 0.0):
            return None
    elif getattr(video, "_VideoFromFile__start_time", 0) or getattr(video, "_VideoFromFile__duration", 0):
        return None
    if getattr(video, "_VideoFromFile__crop", None):
        return None
    return src


def probe(path):
    """The video stream's presented frames as sorted pts, plus timing info.

    Packets are demuxed, not decoded. Frames before pts 0 are left out because
    VideoFromFile drops them too, so the count matches what it decodes.
    """
    key = (path, os.path.getmtime(path), os.path.getsize(path))
    if key in _probe_cache:
        _probe_cache.move_to_end(key)
        return _probe_cache[key]

    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError(f"No video stream in '{os.path.basename(path)}'")
        stream = container.streams.video[0]
        time_base = stream.time_base
        pts = []
        last_duration = 0
        for packet in container.demux(stream):
            if packet.pts is None or packet.size == 0 or getattr(packet, "is_discard", False):
                continue
            if packet.pts >= 0:
                pts.append(packet.pts)
                last_duration = max(last_duration, packet.duration or 0)
        pts.sort()
        if not pts:
            raise ValueError(f"No video frames in '{os.path.basename(path)}'")
        fps = Fraction(stream.average_rate) if stream.average_rate else Fraction(1)
        if not last_duration:
            last_duration = pts[-1] - pts[-2] if len(pts) > 1 else max(1, round(1 / (fps * time_base)))

    info = {"pts": pts, "end_pts": pts[-1] + last_duration, "time_base": time_base, "fps": fps}
    _probe_cache[key] = info
    while len(_probe_cache) > 16:
        _probe_cache.popitem(last=False)
    return info


def window(info, first, last):
    """(start_time, duration) in seconds that keeps 0-based frames first..last."""
    pts, tb = info["pts"], info["time_base"]
    start_time = float((pts[first] + PTS_NUDGE) * tb) if first > 0 else 0.0
    if last >= len(pts) - 1:
        return start_time, 0.0  # to the end of the file
    return start_time, float((pts[last + 1] - pts[first]) * tb)


def clamp_range(total, start_frame, end_frame, keyframe):
    """1-based, inclusive. end 0 = last frame; keyframe 0 = none (the start frame)."""
    start = min(max(1, start_frame), total)
    end = total if end_frame <= 0 else min(max(start, end_frame), total)
    key = start if keyframe <= 0 else min(max(1, keyframe), total)
    return start, end, key


def slice_audio(audio, fps, start, end):
    """The audio under 1-based frames start..end."""
    if not audio:
        return None
    sr = int(audio["sample_rate"])
    s0 = max(0, round((start - 1) * sr / fps))
    s1 = max(s0, round(end * sr / fps))
    return {"waveform": audio["waveform"][..., s0:s1], "sample_rate": sr}


# ---------------------------------------------------------------------------
# Editor preview
# ---------------------------------------------------------------------------

def _temp_path(prefix, node_id, ext):
    import folder_paths

    temp_dir = folder_paths.get_temp_directory()
    os.makedirs(temp_dir, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(node_id or "node"))
    filename = f"{prefix}_{safe}.{ext}"
    return filename, os.path.join(temp_dir, filename)


def preview_size(w, h):
    s = min(1.0, PREVIEW_MAX_SIDE / max(w, h))
    return max(2, round(w * s / 2) * 2), max(2, round(h * s / 2) * 2)


def file_frames(path, size):
    """PIL frames of a file, decoded at reduced size (same frames VideoFromFile keeps)."""
    with av.open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for frame in container.decode(stream):
            if frame.pts is not None and frame.pts < 0:
                continue
            img = frame.to_image(width=size[0], height=size[1])
            if getattr(frame, "rotation", 0):
                img = img.rotate(frame.rotation, expand=True)
            yield img


def tensor_frames(images, size):
    """PIL frames of an IMAGE batch (B, H, W, C), resized."""
    for i in range(images.shape[0]):
        arr = (images[i, :, :, :3].float().clamp(0, 1) * 255).byte().cpu().numpy()
        yield Image.fromarray(arr).resize(size, Image.BILINEAR)


def write_preview(frames, total, fps, node_id):
    """Encode PIL frames to a small H.264 file and a thumbnail strip in temp.

    Returns (video_ref, strip_ref, strip_count, frames_written).
    """
    strip_count = max(1, min(STRIP_TILES, total))
    picks = {min(total - 1, int((j + 0.5) * total / strip_count)): j for j in range(strip_count)}
    tiles = [None] * strip_count

    video_name, video_path = _temp_path("wfio_trim_preview", node_id, "mp4")
    rate = Fraction(fps).limit_denominator(1001000)
    written = 0
    with av.open(video_path, mode="w") as out:
        stream = None
        for img in frames:
            if stream is None:
                w, h = img.size
                w, h = w - w % 2, h - h % 2
                stream = out.add_stream("libx264", rate=rate)
                stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
                stream.options = {"preset": "veryfast", "crf": "26"}
            if img.size != (stream.width, stream.height):
                img = img.crop((0, 0, stream.width, stream.height))
            if written in picks:
                tile_w = max(1, round(STRIP_TILE_H * img.width / img.height))
                tiles[picks[written]] = img.resize((tile_w, STRIP_TILE_H), Image.BILINEAR)
            frame = av.VideoFrame.from_image(img.convert("RGB")).reformat(format="yuv420p")
            for packet in stream.encode(frame):
                out.mux(packet)
            written += 1
        if stream is not None:
            for packet in stream.encode(None):
                out.mux(packet)

    tiles = [t for t in tiles if t is not None]
    strip_ref = None
    if tiles:
        sheet = Image.new("RGB", (sum(t.width for t in tiles), STRIP_TILE_H))
        x = 0
        for t in tiles:
            sheet.paste(t, (x, 0))
            x += t.width
        strip_name, strip_path = _temp_path("wfio_trim_strip", node_id, "jpg")
        sheet.save(strip_path, quality=80)
        strip_ref = {"filename": strip_name, "subfolder": "", "type": "temp"}

    video_ref = {"filename": video_name, "subfolder": "", "type": "temp"}
    return video_ref, strip_ref, len(tiles), written

