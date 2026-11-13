import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Timeline for Workflow IO Video Trim. Same trimming as Load Video (Trim + Keyframe)
// (ComfyUI-VideoTrimmer): white playhead, yellow trim handles that snap to the other
// markers, a cyan keyframe, play, arrow keys. The video comes from the connected input
// after a run (a small H.264 copy and a thumbnail strip the node writes to temp).

const NODE_CLASS = "WorkflowIOVideoTrim";
const TRIM_COLOR = "#e8b923";
const PLAYHEAD_COLOR = "#ffffff";
const KEYFRAME_COLOR = "#22d3ee";
const SNAP_PX = 10;
const HANDLE_W = 9;
const PAD_X = HANDLE_W + 2;
const STRIP_TOP = 12;
const STRIP_H = 52;
const MARKER_ZONE = 12;
const RULER_H = 18;
const CANVAS_H = STRIP_TOP + STRIP_H + MARKER_ZONE + RULER_H;

const widget = (node, name) => node.widgets?.find((w) => w.name === name);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

function el(tag, style = {}, props = {}) {
    const e = document.createElement(tag);
    Object.assign(e.style, style);
    return Object.assign(e, props);
}

const viewURL = (ref) => api.apiURL(`/view?${new URLSearchParams({
    filename: ref.filename, subfolder: ref.subfolder || "", type: ref.type || "temp", t: String(Date.now()),
})}`);

const BUTTON_STYLE = {
    background: "#2a2a2a", color: "#ddd", border: "1px solid #444", borderRadius: "6px",
    font: "12px sans-serif", padding: "4px 10px", cursor: "pointer", whiteSpace: "nowrap",
};

// Frames are numbered from 1, matching the Python node. The timeline places frame f
// at a point: first frame at the left edge, last frame at the right edge. The trim
// handles, the playhead and the keyframe all sit on those points, so a handle dragged
// within SNAP_PX of another marker lands on exactly the same frame.
class VideoTrimEditor {
    constructor(node) {
        this.node = node;
        this.info = null;         // {frames, fps, width, height, strip_count}
        this.loadedKey = null;
        this.playhead = node.properties?.trim_playhead || 1;
        this.focus = "playhead";  // marker shown in the preview and moved by arrow keys
        this.drag = null;
        this.snapTarget = null;
        this.strip = null;
        this.playing = false;
        this.notice = "";

        this.element = el("div", {
            display: "flex", flexDirection: "column", width: "100%", height: "100%", gap: "6px",
            font: "12px sans-serif", color: "#ccc", userSelect: "none",
        });

        this.title = el("div", {
            minHeight: "18px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        });

        this.previewBox = el("div", {
            position: "relative", flex: "1 1 auto", minHeight: "80px", background: "#0b0b0b",
            borderRadius: "8px", overflow: "hidden",
        });
        this.video = el("video", { width: "100%", height: "100%", objectFit: "contain", display: "block" },
            { playsInline: true, preload: "auto", muted: true });
        this.frameLabel = el("div", {
            position: "absolute", left: "8px", bottom: "8px", padding: "3px 8px", borderRadius: "4px",
            background: "rgba(0,0,0,0.7)", font: "12px monospace", color: "#fff", display: "none",
        });
        this.placeholder = el("div", {
            position: "absolute", inset: "0", display: "flex", alignItems: "center", justifyContent: "center",
            color: "#888", font: "12px sans-serif", textAlign: "center", padding: "8px",
        });
        this.previewBox.append(this.video, this.frameLabel, this.placeholder);

        this.timelineRow = el("div", { display: "flex", alignItems: "flex-start", gap: "6px" });
        this.playButton = el("button", {
            ...BUTTON_STYLE, width: "40px", height: `${STRIP_H}px`, marginTop: `${STRIP_TOP}px`,
            padding: "0", fontSize: "16px",
        }, { textContent: "▶", title: "Play the trimmed range (loops)" });
        this.canvas = el("canvas", {
            flex: "1 1 auto", minWidth: "0", height: `${CANVAS_H}px`, touchAction: "none", outline: "none",
        }, { tabIndex: 0 });
        this.timelineRow.append(this.playButton, this.canvas);

        this.footer = el("div", { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" });
        this.readout = el("div", { flex: "1 1 auto", font: "12px monospace", lineHeight: "1.6" });
        this.keyButton = el("button", BUTTON_STYLE, { textContent: "Add keyframe" });
        this.footer.append(this.readout, this.keyButton);

        this.element.append(this.title, this.previewBox, this.timelineRow, this.footer);

        this.canvas.addEventListener("pointerdown", (e) => this.onPointerDown(e));
        this.canvas.addEventListener("pointermove", (e) => this.onPointerMove(e));
        this.canvas.addEventListener("pointerup", (e) => this.onPointerUp(e));
        this.canvas.addEventListener("pointercancel", (e) => this.onPointerUp(e));
        this.canvas.addEventListener("keydown", (e) => this.onKeyDown(e));
        for (const b of [this.playButton, this.keyButton]) b.addEventListener("pointerdown", (e) => e.stopPropagation());
        this.playButton.addEventListener("click", () => this.togglePlay());
        this.keyButton.addEventListener("click", () => this.toggleKeyframe());
        this.video.addEventListener("loadeddata", () => this.showPreview());
        this.video.addEventListener("error", () => {
            if (!this.video.getAttribute("src")) return;
            // A preview from an earlier session is gone once ComfyUI clears its temp folder.
            this.clearSource();
        });
        new ResizeObserver(() => this.draw()).observe(this.canvas);
        this.updateReadout();
    }

    // --- values ---------------------------------------------------------------

    get total() { return this.info?.frames || 0; }
    get start() { return clamp(widget(this.node, "start_frame")?.value || 1, 1, this.total); }
    get end() {
        const v = widget(this.node, "end_frame")?.value || 0;
        return v <= 0 ? this.total : clamp(v, this.start, this.total);
    }
    // "trim + keyframe" mode adds the keyframe; in "trim" mode it is ignored (as the node does).
    get keyframeMode() { return widget(this.node, "mode")?.value === "trim + keyframe"; }
    get keyframe() {
        if (!this.keyframeMode) return 0;
        const v = widget(this.node, "keyframe")?.value || 0;
        return v <= 0 ? 0 : clamp(v, 1, this.total);
    }

    setWidget(name, value) {
        const w = widget(this.node, name);
        if (w && w.value !== value) w.value = value;
    }

    markerFrame(name) {
        return { playhead: this.playhead, start: this.start, end: this.end, keyframe: this.keyframe }[name];
    }

    setMarker(name, frame) {
        const f = clamp(Math.round(frame), 1, this.total);
        if (name === "playhead") {
            this.playhead = f;
            this.node.properties.trim_playhead = f;
        } else if (name === "start") {
            this.setWidget("start_frame", Math.min(f, this.end));
        } else if (name === "end") {
            // The last frame is stored as 0 ("to the end"), which fits videos of any length.
            const end = Math.max(f, this.start);
            this.setWidget("end_frame", end >= this.total ? 0 : end);
        } else if (name === "keyframe") {
            this.setWidget("keyframe", clamp(f, this.start, this.end));
        }
        this.keepKeyframeInTrim();
        this.changed();
    }

    changed() {
        this.updateReadout();
        this.draw();
        this.showPreview();
        this.node.setDirtyCanvas(true, true);
    }

    // Typed values in the number widgets: keep them inside the video.
    normalizeWidgets() {
        if (!this.total) return;
        const start = clamp(widget(this.node, "start_frame").value, 1, this.total);
        this.setWidget("start_frame", start);
        const end = widget(this.node, "end_frame").value;
        if (end > 0) this.setWidget("end_frame", clamp(end, start, this.total));
        this.keepKeyframeInTrim();
    }

    // The keyframe output is also an index into the trimmed video, so the keyframe
    // stays inside the trim: a trim handle dragged past it pushes it along.
    keepKeyframeInTrim() {
        if (!this.keyframeMode) return;
        const key = widget(this.node, "keyframe")?.value || 0;
        if (key > 0) this.setWidget("keyframe", clamp(key, this.start, this.end));
    }

    resetTrim() {
        this.setWidget("start_frame", 1);
        this.setWidget("end_frame", 0);
        this.setWidget("keyframe", 0);
        this.playhead = 1;
    }

    // --- source ---------------------------------------------------------------

    inputLinked() {
        return this.node.inputs?.find((i) => i.name === "video")?.link != null;
    }

    clearSource() {
        this.pause();
        this.info = null;
        this.strip = null;
        this.loadedKey = null;
        this.video.removeAttribute("src");
        this.video.load();
        this.changed();
    }

    refreshSource() {
        const p = this.node.properties ?? {};
        if (!this.inputLinked() || !p.trim_video?.filename || !p.trim_info) {
            this.clearSource();
            return;
        }
        const key = `${p.trim_video.filename}:${p.trim_run}`;
        if (key === this.loadedKey) return;
        this.pause();
        this.loadedKey = key;
        const prevTotal = this.info?.frames;
        this.info = p.trim_info;
        this.notice = "";
        if (prevTotal && prevTotal !== this.info.frames) {
            this.resetTrim();
            this.notice = "New video: trim reset to the whole video.";
        } else {
            this.normalizeWidgets();
        }
        this.playhead = clamp(this.playhead, 1, this.total);
        this.node.properties.trim_playhead = this.playhead;
        this.strip = null;
        if (p.trim_strip?.filename) {
            const img = new Image();
            img.onload = () => {
                if (this.loadedKey !== key) return;
                this.strip = { img, count: Math.max(1, this.info.strip_count || 1) };
                this.draw();
            };
            img.src = viewURL(p.trim_strip);
        }
        this.video.src = viewURL(p.trim_video);
        this.changed();
    }

    onExecuted(message) {
        const video = message?.trim_video?.[0], info = message?.trim_info?.[0];
        if (!video || !info) return;
        const props = this.node.properties;
        props.trim_video = video;
        props.trim_strip = message.trim_strip?.[0] ?? null;
        props.trim_info = info;
        props.trim_run = Date.now();
        this.refreshSource();
    }

    // --- preview --------------------------------------------------------------

    // The preview is constant frame rate: frame f (from 1) shows from (f-1)/fps to f/fps.
    frameTime(f) { return (f - 0.5) / this.info.fps; }

    timeToFrame(time) { return clamp(Math.floor(time * this.info.fps + 1e-6) + 1, 1, this.total); }

    showPreview() {
        const linked = this.inputLinked();
        this.placeholder.style.display = this.info ? "none" : "flex";
        this.placeholder.textContent = linked ? "Run the workflow once to load the video" : "Connect a video";
        if (!this.info) {
            this.frameLabel.style.display = "none";
            return;
        }
        const name = this.focus === "keyframe" && !this.keyframe ? "playhead" : this.focus;
        const f = this.markerFrame(name);
        const label = { playhead: "Frame", start: "Start", end: "End", keyframe: "Keyframe" }[name];
        this.frameLabel.style.display = "block";
        this.frameLabel.textContent = `${label} ${f}`;
        this.frameLabel.style.color = name === "keyframe" ? KEYFRAME_COLOR : name === "playhead" ? "#fff" : TRIM_COLOR;
        if (this.playing) return;
        if (this.video.readyState >= 1) this.video.currentTime = this.frameTime(f);
    }

    togglePlay() {
        if (this.playing) {
            this.pause();
            return;
        }
        if (!this.info) return;
        if (this.playhead < this.start || this.playhead >= this.end) this.playhead = this.start;
        this.focus = "playhead";
        this.video.currentTime = this.frameTime(this.playhead);
        this.playing = true;
        this.playButton.textContent = "❚❚";
        this.video.play().catch(() => this.pause());
        const tick = () => {
            if (!this.playing) return;
            const f = this.timeToFrame(this.video.currentTime);
            if (f > this.end || this.video.ended) {
                this.video.currentTime = this.frameTime(this.start);
                if (this.video.paused) this.video.play().catch(() => this.pause());
                this.playhead = this.start;
            } else {
                this.playhead = Math.max(f, this.start);
            }
            this.updateReadout();
            this.draw();
            this.frameLabel.textContent = `Frame ${this.playhead}`;
            requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    }

    pause() {
        if (!this.playing) return;
        this.playing = false;
        this.video.pause();
        this.playButton.textContent = "▶";
        this.node.properties.trim_playhead = this.playhead;
        this.showPreview();
    }

    // Shows the keyframe field and button only in "trim + keyframe" mode; leaving that
    // mode clears the keyframe so the saved value stays at the default.
    syncMode() {
        const on = this.keyframeMode;
        const kw = widget(this.node, "keyframe");
        if (kw) {
            if (!on && kw.value) kw.value = 0;
            kw.hidden = !on;
        }
        if (!on && this.focus === "keyframe") this.focus = "playhead";
        this.keyButton.style.display = on ? "" : "none";
        this.changed();
    }

    toggleKeyframe() {
        if (!this.info || !this.keyframeMode) return;
        if (this.keyframe) {
            this.setWidget("keyframe", 0);
            if (this.focus === "keyframe") this.focus = "playhead";
        } else {
            // Added at the playhead (or the nearest trim edge), then drag it.
            this.setWidget("keyframe", clamp(this.playhead, this.start, this.end));
            this.focus = "keyframe";
        }
        this.changed();
    }

    updateReadout() {
        this.keyButton.textContent = this.keyframe ? "Remove keyframe" : "Add keyframe";
        this.keyButton.style.borderColor = this.keyframe ? "#444" : KEYFRAME_COLOR;
        this.playButton.disabled = !this.info;
        this.playButton.style.opacity = this.info ? "1" : "0.35";
        if (!this.info) {
            this.readout.textContent = "";
            this.title.textContent = "";
            return;
        }
        const fps = this.info.fps;
        const fpsText = Number.isInteger(fps) ? fps : fps.toFixed(3);
        const n = this.end - this.start + 1;
        this.title.innerHTML = "";
        this.title.append(
            el("span", { color: "#eee" }, { textContent: this.notice || `Your video has ${this.total} frames` }),
            el("span", { color: "#777" }, { textContent: `  ·  ${this.info.width}×${this.info.height} @ ${fpsText}fps` }),
        );
        this.readout.innerHTML = "";
        const item = (label, value, color) => el("span", { display: "inline-block", marginRight: "14px", whiteSpace: "nowrap" }, {
            innerHTML: `<span style="color:#888">${label}</span> <span style="color:${color}">${value}</span>`,
        });
        this.readout.append(
            item("Start Frame:", this.start, "#fff"),
            item("End Frame:", this.end, "#fff"),
            item("Duration:", `${n} Frames <span style="color:#777">(${(n / fps).toFixed(1)}s @ ${fpsText}fps)</span>`, "#fff"),
        );
        if (this.keyframeMode) {
            this.readout.append(item("Keyframe:", this.keyframe
                ? `${this.keyframe} <span style="color:#777">(index ${this.keyframe - this.start} in trim)</span>`
                : "none", this.keyframe ? KEYFRAME_COLOR : "#666"));
        }
    }

    // --- timeline geometry ----------------------------------------------------

    get trackWidth() { return Math.max(1, this.canvas.clientWidth - 2 * PAD_X); }

    frameToX(f) {
        return this.total > 1 ? PAD_X + ((f - 1) / (this.total - 1)) * this.trackWidth : PAD_X + this.trackWidth / 2;
    }

    xToFrame(x) {
        return this.total > 1 ? clamp(Math.round(1 + ((x - PAD_X) / this.trackWidth) * (this.total - 1)), 1, this.total) : 1;
    }

    pointer(e) {
        const r = this.canvas.getBoundingClientRect();
        // DOM widgets are CSS-scaled with the graph zoom; convert to unscaled canvas px.
        // Grab and snap distances stay constant on screen at any zoom.
        this.zoom = r.width / this.canvas.clientWidth || 1;
        return [(e.clientX - r.left) / this.zoom, (e.clientY - r.top) / this.zoom];
    }

    hitTest(x, y) {
        const z = Math.min(1, this.zoom || 1);
        const near = (name, px) => Math.abs(x - this.frameToX(this.markerFrame(name))) <= px / z;
        const stripBottom = STRIP_TOP + STRIP_H;
        if (y < STRIP_TOP && near("playhead", 9)) return "playhead";
        if (this.keyframe && y > stripBottom - 4 && y < stripBottom + MARKER_ZONE && near("keyframe", 9)) return "keyframe";
        if (y >= STRIP_TOP - 2 && y <= stripBottom + 2) {
            const xs = this.frameToX(this.start), xe = this.frameToX(this.end);
            const ds = x <= xs + 3 ? Math.abs(x - (xs - HANDLE_W / 2)) : Infinity;
            const de = x >= xe - 3 ? Math.abs(x - (xe + HANDLE_W / 2)) : Infinity;
            if (Math.min(ds, de) <= HANDLE_W / z) return ds <= de ? "start" : "end";
        }
        if (near("playhead", 4)) return "playhead";
        if (this.keyframe && near("keyframe", 4)) return "keyframe";
        return null;
    }

    snap(name, x) {
        let frame = this.xToFrame(x);
        this.snapTarget = null;
        let best = SNAP_PX / (this.zoom || 1);
        for (const other of ["playhead", "keyframe", "start", "end"]) {
            if (other === name || (other === "keyframe" && !this.keyframe)) continue;
            if ((name === "start" && other === "end") || (name === "end" && other === "start")) continue;
            const f = this.markerFrame(other);
            const d = Math.abs(this.frameToX(f) - x);
            if (d <= best) {
                best = d;
                frame = f;
                this.snapTarget = other;
            }
        }
        return frame;
    }

    // --- interaction ----------------------------------------------------------

    onPointerDown(e) {
        if (!this.info || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        this.canvas.focus();
        this.pause();
        const [x, y] = this.pointer(e);
        let name = this.hitTest(x, y);
        if (!name) {
            name = "playhead";  // click on the strip: jump the playhead there
            this.setMarker("playhead", this.xToFrame(x));
        }
        this.drag = { name, grab: x - this.frameToX(this.markerFrame(name)) };
        this.focus = name;
        this.canvas.setPointerCapture(e.pointerId);
        this.changed();
    }

    onPointerMove(e) {
        if (!this.info) return;
        const [x, y] = this.pointer(e);
        if (!this.drag) {
            const hit = this.hitTest(x, y);
            this.canvas.style.cursor = hit === "start" || hit === "end" ? "ew-resize" : hit ? "grab" : "pointer";
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        this.canvas.style.cursor = "grabbing";
        this.setMarker(this.drag.name, this.snap(this.drag.name, x - this.drag.grab));
    }

    onPointerUp(e) {
        if (!this.drag) return;
        this.canvas.releasePointerCapture?.(e.pointerId);
        this.drag = null;
        this.snapTarget = null;
        // Pointer events skip the change tracker's mouseup; record the undo step.
        app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
        this.draw();
    }

    onKeyDown(e) {
        if (!this.info) return;
        const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
        if (e.key === " ") {
            this.togglePlay();
        } else if (step) {
            this.pause();
            const name = this.focus === "keyframe" && !this.keyframe ? "playhead" : this.focus;
            this.setMarker(name, this.markerFrame(name) + step * (e.shiftKey ? 10 : 1));
        } else {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
    }

    // --- drawing --------------------------------------------------------------

    draw() {
        const c = this.canvas;
        const dpr = window.devicePixelRatio || 1;
        const W = c.clientWidth, H = CANVAS_H;
        if (!W) return;
        if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
            c.width = Math.round(W * dpr);
            c.height = Math.round(H * dpr);
        }
        const ctx = c.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);

        const x0 = PAD_X, x1 = PAD_X + this.trackWidth, top = STRIP_TOP, bottom = STRIP_TOP + STRIP_H;
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(x0, top, x1 - x0, STRIP_H, 6);
        ctx.clip();
        ctx.fillStyle = "#1c1c1c";
        ctx.fillRect(x0, top, x1 - x0, STRIP_H);
        if (!this.info) {
            ctx.restore();
            return;
        }
        if (this.strip) {
            // The strip holds up to 40 evenly spaced frames; show as many as fit the width.
            const { img, count: available } = this.strip;
            const tw = img.width / available;
            const count = clamp(Math.round((x1 - x0) / (STRIP_H * (tw / img.height))), 1, available);
            const cell = (x1 - x0) / count;
            const scale = Math.max(cell / tw, STRIP_H / img.height);
            const sw = cell / scale, sh = STRIP_H / scale;
            for (let j = 0; j < count; j++) {
                const k = Math.min(available - 1, Math.floor(((j + 0.5) * available) / count));
                ctx.drawImage(img, k * tw + (tw - sw) / 2, (img.height - sh) / 2, sw, sh, x0 + j * cell, top, cell + 0.5, STRIP_H);
            }
        }
        const xs = this.frameToX(this.start), xe = this.frameToX(this.end);
        ctx.fillStyle = "rgba(0,0,0,0.6)";
        ctx.fillRect(x0, top, xs - x0, STRIP_H);
        ctx.fillRect(xe, top, x1 - xe, STRIP_H);
        ctx.restore();

        // Trim box with a handle on each side.
        ctx.strokeStyle = TRIM_COLOR;
        ctx.lineWidth = 3;
        ctx.strokeRect(xs, top + 1.5, xe - xs, STRIP_H - 3);
        for (const [side, x] of [["start", xs - HANDLE_W], ["end", xe]]) {
            ctx.fillStyle = TRIM_COLOR;
            ctx.beginPath();
            ctx.roundRect(x, top, HANDLE_W, STRIP_H, side === "start" ? [5, 0, 0, 5] : [0, 5, 5, 0]);
            ctx.fill();
            ctx.fillStyle = "rgba(0,0,0,0.45)";
            ctx.fillRect(x + HANDLE_W / 2 - 1, top + STRIP_H / 2 - 8, 2, 16);
            if (this.snapTarget && this.drag?.name === side) {
                ctx.strokeStyle = "#fff";
                ctx.lineWidth = 1.5;
                ctx.strokeRect(x - 1, top - 1, HANDLE_W + 2, STRIP_H + 2);
            }
        }

        // Keyframe: cyan line with a diamond under the strip.
        if (this.keyframe) {
            const xk = this.frameToX(this.keyframe);
            ctx.fillStyle = KEYFRAME_COLOR;
            ctx.fillRect(xk - 1, top, 2, STRIP_H);
            ctx.beginPath();
            ctx.moveTo(xk, bottom + 1);
            ctx.lineTo(xk + 6, bottom + 7);
            ctx.lineTo(xk, bottom + 13);
            ctx.lineTo(xk - 6, bottom + 7);
            ctx.closePath();
            ctx.fill();
            if (this.focus === "keyframe" || this.snapTarget === "keyframe") {
                ctx.strokeStyle = "#fff";
                ctx.lineWidth = 1;
                ctx.stroke();
            }
        }

        // Playhead: white line with a triangle on top.
        const xp = this.frameToX(this.playhead);
        ctx.fillStyle = PLAYHEAD_COLOR;
        ctx.fillRect(xp - 1, top - 2, 2, STRIP_H + 4);
        ctx.beginPath();
        ctx.moveTo(xp - 7, 0);
        ctx.lineTo(xp + 7, 0);
        ctx.lineTo(xp, top);
        ctx.closePath();
        ctx.fill();
        if (this.snapTarget === "playhead") {
            ctx.strokeStyle = TRIM_COLOR;
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }

        // Ruler: frame numbers at round steps, starting from frame 1 like the readout.
        const minGap = 44;
        const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 25000, 50000, 100000];
        const pxPerFrame = this.total > 1 ? this.trackWidth / (this.total - 1) : this.trackWidth;
        const step = steps.find((s) => s * pxPerFrame >= minGap) || steps[steps.length - 1];
        ctx.fillStyle = "#888";
        ctx.font = "10px sans-serif";
        ctx.textBaseline = "bottom";
        const labelY = H - 2;
        const lastX = this.frameToX(this.total);
        for (let f = 1; f <= this.total; f += step) {
            const x = this.frameToX(f);
            if (f !== 1 && lastX - x < minGap * 0.8) break;  // leave room for the last frame's label
            ctx.textAlign = f === 1 ? "left" : "center";
            ctx.fillText(String(f), f === 1 ? x - 2 : x, labelY);
        }
        if (this.total > 1) {
            ctx.textAlign = "right";
            ctx.fillText(String(this.total), lastX + 2, labelY);
        }
    }
}

app.registerExtension({
    name: "workflow_io.VideoTrim",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this.properties ??= {};
            const editor = new VideoTrimEditor(this);
            this.videoTrimEditor = editor;

            for (const name of ["start_frame", "end_frame", "keyframe"]) {
                const w = widget(this, name);
                if (!w) continue;
                const callback = w.callback;
                w.callback = function () {
                    const r = callback?.apply(this, arguments);
                    editor.normalizeWidgets();
                    if (name !== "keyframe" || w.value) {
                        editor.focus = name === "start_frame" ? "start" : name === "end_frame" ? "end" : "keyframe";
                    }
                    editor.changed();
                    return r;
                };
            }

            const modeWidget = widget(this, "mode");
            if (modeWidget) {
                const callback = modeWidget.callback;
                modeWidget.callback = function () {
                    const r = callback?.apply(this, arguments);
                    editor.syncMode();
                    return r;
                };
            }

            // Display only: not saved (both flags, or the frontend still writes a value).
            const view = this.addDOMWidget("video_trim_editor", "video_trim_editor", editor.element, {
                serialize: false,
                hideOnZoom: false,
                getMinHeight: () => 380,
            });
            view.serialize = false;
            this.setSize([Math.max(this.size[0], 520), Math.max(this.size[1], 820)]);
            editor.syncMode();
            requestAnimationFrame(() => editor.refreshSource());
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            this.videoTrimEditor?.onExecuted(message);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const r = onConnectionsChange?.apply(this, arguments);
            this.videoTrimEditor?.refreshSource();
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            const editor = this.videoTrimEditor;
            if (editor) {
                editor.playhead = this.properties?.trim_playhead || 1;
                editor.syncMode();
                editor.refreshSource();
            }
            return r;
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this.videoTrimEditor?.pause();
            return onRemoved?.apply(this, arguments);
        };
    },
});
