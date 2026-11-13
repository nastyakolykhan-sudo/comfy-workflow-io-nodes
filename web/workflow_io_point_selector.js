import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Viewport for Workflow IO Point Selector: the connected image (after a run) with
// positive (green) and negative (red) points. Click adds a positive point, shift-click
// or right-click a negative one, drag moves a point, right-click on a point deletes it.
// Points are stored in source pixels as JSON [{"x": int, "y": int}, ...], the format
// SAM3 Detect, SAM2, SeC and KJNodes Points Editor use.

const NODE_CLASS = "WorkflowIOPointSelector";
const COLORS = { positive: "#22c55e", negative: "#ef4444" };
const FIELDS = { positive: "positive_points", negative: "negative_points" };
const HIT_PX = 10;
const DOT_PX = 6;

const widget = (node, name) => node.widgets?.find((w) => w.name === name);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

function readPoints(text) {
    try {
        const raw = JSON.parse(text || "[]");
        const list = Array.isArray(raw) ? raw : [raw];
        return list
            .map((p) => (Array.isArray(p) ? { x: p[0], y: p[1] } : p))
            .filter((p) => p && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)))
            .map((p) => ({ x: Math.round(Number(p.x)), y: Math.round(Number(p.y)) }));
    } catch {
        return [];
    }
}

class PointEditor {
    constructor(node) {
        this.node = node;
        this.image = null;
        this.sourceSize = null;
        this.loadedKey = null;
        this.drag = null;
        this.notice = "";

        this.element = document.createElement("div");
        Object.assign(this.element.style, {
            display: "flex", flexDirection: "column", width: "100%", height: "100%", gap: "4px",
        });
        this.canvas = document.createElement("canvas");
        Object.assign(this.canvas.style, {
            flex: "1 1 auto", width: "100%", minHeight: "0", cursor: "crosshair",
            touchAction: "none", borderRadius: "4px",
        });
        this.info = document.createElement("div");
        Object.assign(this.info.style, {
            font: "11px monospace", color: "#aaa", textAlign: "center",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        });
        this.element.append(this.canvas, this.info);

        this.canvas.addEventListener("pointerdown", (e) => this.onPointerDown(e));
        this.canvas.addEventListener("pointermove", (e) => this.onPointerMove(e));
        this.canvas.addEventListener("pointerup", (e) => this.onPointerUp(e));
        this.canvas.addEventListener("pointercancel", (e) => this.onPointerUp(e));
        this.canvas.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            e.stopPropagation();
        });
        new ResizeObserver(() => this.draw()).observe(this.canvas);
    }

    ready() {
        return !!(this.image && this.sourceSize);
    }

    inputLinked() {
        return this.node.inputs?.find((i) => i.name === "image")?.link != null;
    }

    points(kind) {
        return readPoints(widget(this.node, FIELDS[kind])?.value);
    }

    setPoints(kind, list) {
        const w = widget(this.node, FIELDS[kind]);
        if (w) w.value = list.length ? JSON.stringify(list) : "";
        this.node.setDirtyCanvas(true, true);
    }

    clearPoints() {
        this.setPoints("positive", []);
        this.setPoints("negative", []);
        this.draw();
        app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
    }

    layout() {
        const cw = this.canvas.clientWidth, ch = this.canvas.clientHeight, pad = 8;
        const [W, H] = this.sourceSize;
        const k = Math.min((cw - 2 * pad) / W, (ch - 2 * pad) / H);
        return { k, ox: (cw - W * k) / 2, oy: (ch - H * k) / 2 };
    }

    pointerPosition(e) {
        const rect = this.canvas.getBoundingClientRect();
        const sx = (e.clientX - rect.left) * (this.canvas.clientWidth / rect.width);
        const sy = (e.clientY - rect.top) * (this.canvas.clientHeight / rect.height);
        const { k, ox, oy } = this.layout();
        const [W, H] = this.sourceSize;
        return {
            sx, sy,
            x: clamp(Math.floor((sx - ox) / k), 0, W - 1),
            y: clamp(Math.floor((sy - oy) / k), 0, H - 1),
            inside: sx >= ox && sy >= oy && sx <= ox + W * k && sy <= oy + H * k,
        };
    }

    // The point under the pointer, nearest first: {kind, index}.
    hitTest(p) {
        const { k, ox, oy } = this.layout();
        let best = null, bestD = HIT_PX;
        for (const kind of ["positive", "negative"]) {
            this.points(kind).forEach((pt, index) => {
                const d = Math.hypot((pt.x + 0.5) * k + ox - p.sx, (pt.y + 0.5) * k + oy - p.sy);
                if (d <= bestD) {
                    bestD = d;
                    best = { kind, index };
                }
            });
        }
        return best;
    }

    onPointerDown(e) {
        if (!this.ready() || (e.button !== 0 && e.button !== 2)) return;
        e.preventDefault();
        e.stopPropagation();
        const p = this.pointerPosition(e);
        const hit = this.hitTest(p);
        if (hit && e.button === 2) {
            const list = this.points(hit.kind);
            list.splice(hit.index, 1);
            this.setPoints(hit.kind, list);
        } else if (hit) {
            this.canvas.setPointerCapture(e.pointerId);
            this.drag = hit;
        } else if (p.inside) {
            const kind = e.button === 2 || e.shiftKey ? "negative" : "positive";
            const list = this.points(kind);
            list.push({ x: p.x, y: p.y });
            this.setPoints(kind, list);
            this.canvas.setPointerCapture(e.pointerId);
            this.drag = { kind, index: list.length - 1 };
        }
        this.draw();
    }

    onPointerMove(e) {
        if (!this.ready()) return;
        const p = this.pointerPosition(e);
        if (!this.drag) {
            this.canvas.style.cursor = this.hitTest(p) ? "grab" : p.inside ? "crosshair" : "default";
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const list = this.points(this.drag.kind);
        if (!list[this.drag.index]) return;
        list[this.drag.index] = { x: p.x, y: p.y };
        this.setPoints(this.drag.kind, list);
        this.canvas.style.cursor = "grabbing";
        this.draw();
    }

    onPointerUp(e) {
        if (this.canvas.hasPointerCapture?.(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
        if (this.drag) e.stopPropagation();
        this.drag = null;
        // Pointer events skip the change tracker's mouseup; record the undo step.
        app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
        this.draw();
    }

    draw() {
        const c = this.canvas, dpr = window.devicePixelRatio || 1;
        const cw = c.clientWidth, ch = c.clientHeight;
        if (!cw || !ch) return;
        if (c.width !== Math.round(cw * dpr) || c.height !== Math.round(ch * dpr)) {
            c.width = Math.round(cw * dpr);
            c.height = Math.round(ch * dpr);
        }
        const ctx = c.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = "#1b1b1b";
        ctx.fillRect(0, 0, cw, ch);

        if (!this.ready()) {
            ctx.fillStyle = "#888";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "center";
            const text = this.inputLinked() ? "Run the workflow once to load the image" : "Connect an image";
            ctx.fillText(text, cw / 2, ch / 2);
            this.info.textContent = "";
            return;
        }

        const { k, ox, oy } = this.layout();
        const [W, H] = this.sourceSize;
        ctx.drawImage(this.image, ox, oy, W * k, H * k);

        ctx.font = "bold 10px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const counts = {};
        for (const kind of ["negative", "positive"]) {
            const list = this.points(kind);
            counts[kind] = list.length;
            list.forEach((pt, i) => {
                const x = (pt.x + 0.5) * k + ox, y = (pt.y + 0.5) * k + oy;
                ctx.beginPath();
                ctx.arc(x, y, DOT_PX, 0, Math.PI * 2);
                ctx.fillStyle = COLORS[kind];
                ctx.fill();
                ctx.lineWidth = 2;
                ctx.strokeStyle = "#fff";
                ctx.stroke();
                ctx.fillStyle = "#fff";
                ctx.fillText(kind === "positive" ? "+" : "−", x, y + 0.5);
                // White label with a dark outline, readable on any image.
                ctx.lineWidth = 3;
                ctx.strokeStyle = "rgba(0,0,0,0.8)";
                ctx.strokeText(String(i + 1), x + DOT_PX + 6, y - DOT_PX - 2);
                ctx.fillText(String(i + 1), x + DOT_PX + 6, y - DOT_PX - 2);
            });
        }
        this.info.textContent = this.notice ||
            `${counts.positive} positive · ${counts.negative} negative · ${W}×${H} · ` +
            "click +, shift/right-click −, drag to move, right-click a point to delete";
    }

    loadImage(key, params, size) {
        if (key === this.loadedKey) return;
        this.loadedKey = key;
        params.set("t", String(Date.now()));
        const img = new Image();
        img.onload = () => {
            if (this.loadedKey !== key) return;
            const prev = this.sourceSize;
            this.image = img;
            this.sourceSize = size;
            this.notice = "";
            if (prev && (prev[0] !== size[0] || prev[1] !== size[1]) &&
                (this.points("positive").length || this.points("negative").length)) {
                this.setPoints("positive", []);
                this.setPoints("negative", []);
                this.notice = "New image size: points cleared.";
            }
            this.draw();
        };
        img.onerror = () => {
            // A preview from an earlier session is gone once ComfyUI clears its temp folder.
            if (this.loadedKey !== key) return;
            this.loadedKey = null;
            this.image = null;
            this.draw();
        };
        img.src = api.apiURL(`/view?${params}`);
    }

    refreshSource() {
        const props = this.node.properties ?? {};
        const preview = props.points_preview, size = props.points_source_size;
        if (!this.inputLinked() || !preview?.filename || !size) {
            this.loadedKey = null;
            this.image = null;
            this.draw();
            return;
        }
        const params = new URLSearchParams({
            filename: preview.filename, type: preview.type || "temp", subfolder: preview.subfolder || "",
        });
        this.loadImage(`${preview.filename}:${size}:${props.points_run}`, params, size);
    }

    onExecuted(message) {
        const preview = message?.points_preview?.[0];
        if (!preview) return;
        const props = this.node.properties;
        props.points_preview = preview;
        props.points_source_size = message.points_source_size;
        props.points_run = Date.now();
        this.refreshSource();
    }
}

app.registerExtension({
    name: "workflow_io.PointSelector",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this.properties ??= {};
            const editor = new PointEditor(this);
            this.pointEditor = editor;

            for (const name of Object.values(FIELDS)) {
                const w = widget(this, name);
                if (!w) continue;
                const callback = w.callback;
                w.callback = function () {
                    const r = callback?.apply(this, arguments);
                    editor.draw();
                    return r;
                };
            }

            const clear = this.addWidget("button", "Clear points", null, () => editor.clearPoints(),
                { serialize: false });
            clear.serialize = false;

            // Display only: not saved (both flags, or the frontend still writes a value).
            const view = this.addDOMWidget("point_editor", "point_editor", editor.element, {
                serialize: false,
                hideOnZoom: false,
                getMinHeight: () => 300,
            });
            view.serialize = false;
            this.setSize([Math.max(this.size[0], 400), Math.max(this.size[1], 720)]);
            requestAnimationFrame(() => editor.refreshSource());
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            this.pointEditor?.onExecuted(message);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const r = onConnectionsChange?.apply(this, arguments);
            this.pointEditor?.refreshSource();
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            this.pointEditor?.refreshSource();
            return r;
        };
    },
});
