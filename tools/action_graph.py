"""Reference for apps that run a workflow's actions (Workflow IO Text Output with ``action``).

An action is a Workflow IO Text Output whose ``action`` field is set (a button label,
e.g. "Suggest prompt"). The app runs it on its own: it sends only the nodes that feed
that output, reads the returned text file, and puts the text into the input named by
``fills`` for the user to read or edit. The normal run leaves action outputs out, so
their branch only runs if something else still needs it.

Deployments don't honour ComfyUI's ``partial_execution_targets``, so the app sends a
trimmed workflow instead: ComfyUI runs every output node it is given.

    python tools/action_graph.py workflow_api.json            # list actions and their inputs
    python tools/action_graph.py workflow_api.json --write    # also write <name>.<action>.json
                                                              # and <name>.main.json
"""

import json
import re
import sys
from pathlib import Path

TEXT_OUTPUT = "WorkflowIOTextOutput"


def _links(node):
    """Node ids this node takes inputs from."""
    return [v[0] for v in node.get("inputs", {}).values()
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int))]


def actions(api):
    """{node_id: {"action", "fills", "output_name"}} for every Text Output with an action."""
    found = {}
    for node_id, node in api.items():
        inputs = node.get("inputs", {})
        if node.get("class_type") == TEXT_OUTPUT and str(inputs.get("action") or "").strip():
            found[str(node_id)] = {
                "action": inputs["action"].strip(),
                "fills": str(inputs.get("fills") or "").strip(),
                "output_name": inputs.get("output_name") or "text",
            }
    return found


def action_workflow(api, output_id):
    """The workflow trimmed to one output and every node that feeds it."""
    keep, todo = set(), [str(output_id)]
    while todo:
        node_id = todo.pop()
        if node_id in keep or node_id not in api:
            continue
        keep.add(node_id)
        todo.extend(str(i) for i in _links(api[node_id]))
    return {k: v for k, v in api.items() if k in keep}


def main_workflow(api):
    """The workflow for the normal run: action outputs left out."""
    skip = set(actions(api))
    return {k: v for k, v in api.items() if k not in skip}


def needed_inputs(api):
    """param_names of the Workflow IO inputs in this (possibly trimmed) workflow."""
    return [node["inputs"].get("param_name") for node in api.values()
            if str(node.get("class_type", "")).startswith("WorkflowIO") and str(node.get("class_type")).endswith("Input")
            and node.get("inputs", {}).get("param_name")]


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "action"


if __name__ == "__main__":
    path = Path(sys.argv[1])
    api = json.loads(path.read_text())
    found = actions(api)
    if not found:
        print("No actions (no Workflow IO Text Output with 'action' set).")
    for node_id, info in found.items():
        trimmed = action_workflow(api, node_id)
        print(f"#{node_id} '{info['action']}' fills '{info['fills'] or '-'}': runs {len(trimmed)} of {len(api)} nodes, "
              f"needs inputs {needed_inputs(trimmed)}")
        if "--write" in sys.argv:
            out = path.with_name(f"{path.stem}.{_slug(info['action'])}.json")
            out.write_text(json.dumps(trimmed, indent=1))
            print(f"  wrote {out.name}")
    if found and "--write" in sys.argv:
        out = path.with_name(f"{path.stem}.main.json")
        out.write_text(json.dumps(main_workflow(api), indent=1))
        print(f"wrote {out.name} (normal run, {len(main_workflow(api))} nodes)")
