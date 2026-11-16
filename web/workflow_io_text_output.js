import { app } from "../../scripts/app.js";

// Workflow IO Text Output: shows the returned text on the node after a run, read-only.
// Display only: the text is not saved with the workflow (it comes from the last run).

const NODE_CLASS = "WorkflowIOTextOutput";

app.registerExtension({
    name: "workflow_io.TextOutput",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const box = document.createElement("textarea");
            box.readOnly = true;
            box.placeholder = "Run the workflow to see the text";
            Object.assign(box.style, {
                width: "100%", height: "100%", boxSizing: "border-box", resize: "none",
                font: "12px sans-serif", color: "#ddd", background: "#1e1e1e",
                border: "1px solid #444", borderRadius: "4px", padding: "6px",
            });
            this.textOutputBox = box;
            // Both flags, or the frontend still writes a value into widgets_values.
            const view = this.addDOMWidget("text_preview", "text_preview", box, {
                serialize: false,
                hideOnZoom: false,
                getMinHeight: () => 120,
            });
            view.serialize = false;
            this.setSize([Math.max(this.size[0], 360), Math.max(this.size[1], 300)]);
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const text = message?.text;
            if (this.textOutputBox && text !== undefined) {
                this.textOutputBox.value = Array.isArray(text) ? text.join("\n") : String(text);
            }
        };
    },
});
