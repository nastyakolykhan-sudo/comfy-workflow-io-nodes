"""Comfy Workflow IO Nodes — ComfyUI custom-node entrypoint.

ComfyUI loads this package from ``custom_nodes/`` and reads NODE_CLASS_MAPPINGS
and NODE_DISPLAY_NAME_MAPPINGS at boot.
"""

from .api_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

# Frontend for Workflow IO Image Reframe's viewport.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
