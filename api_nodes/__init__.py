"""Workflow IO node pack — aggregates the class + display-name mappings."""

from .inputs import (
    WorkflowIOTextInput,
    WorkflowIOIntInput,
    WorkflowIOFloatInput,
    WorkflowIOBoolInput,
    WorkflowIOEnumInput,
    WorkflowIOSeedInput,
    WorkflowIOImageInput,
    WorkflowIOVideoInput,
)
from .reframe import WorkflowIOImageVideoReframe, WorkflowIOImageVideoReframeComposite
from .trim import WorkflowIOVideoTrim, WorkflowIOVideoTrimComposite
from .points import WorkflowIOPointSelector
from .outputs import (
    WorkflowIOImageOutput,
    WorkflowIOVideoOutput,
    WorkflowIO3DOutput,
)

NODE_CLASS_MAPPINGS = {
    # Inputs
    "WorkflowIOTextInput": WorkflowIOTextInput,
    "WorkflowIOIntInput": WorkflowIOIntInput,
    "WorkflowIOFloatInput": WorkflowIOFloatInput,
    "WorkflowIOBoolInput": WorkflowIOBoolInput,
    "WorkflowIOEnumInput": WorkflowIOEnumInput,
    "WorkflowIOSeedInput": WorkflowIOSeedInput,
    "WorkflowIOImageInput": WorkflowIOImageInput,
    "WorkflowIOVideoInput": WorkflowIOVideoInput,
    "WorkflowIOImageVideoReframe": WorkflowIOImageVideoReframe,
    "WorkflowIOImageVideoReframeComposite": WorkflowIOImageVideoReframeComposite,
    "WorkflowIOVideoTrim": WorkflowIOVideoTrim,
    "WorkflowIOVideoTrimComposite": WorkflowIOVideoTrimComposite,
    "WorkflowIOPointSelector": WorkflowIOPointSelector,
    # Outputs
    "WorkflowIOImageOutput": WorkflowIOImageOutput,
    "WorkflowIOVideoOutput": WorkflowIOVideoOutput,
    "WorkflowIO3DOutput": WorkflowIO3DOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WorkflowIOTextInput": "Workflow IO Text Input",
    "WorkflowIOIntInput": "Workflow IO Int Input",
    "WorkflowIOFloatInput": "Workflow IO Float Input",
    "WorkflowIOBoolInput": "Workflow IO Bool Input",
    "WorkflowIOEnumInput": "Workflow IO Enum Input",
    "WorkflowIOSeedInput": "Workflow IO Seed Input",
    "WorkflowIOImageInput": "Workflow IO Image Input",
    "WorkflowIOVideoInput": "Workflow IO Video Input",
    "WorkflowIOImageVideoReframe": "Workflow IO Image/Video Reframe",
    "WorkflowIOImageVideoReframeComposite": "Workflow IO Image/Video Reframe Composite",
    "WorkflowIOVideoTrim": "Workflow IO Video Trim",
    "WorkflowIOVideoTrimComposite": "Workflow IO Video Trim Composite",
    "WorkflowIOPointSelector": "Workflow IO Point Selector",
    "WorkflowIOImageOutput": "Workflow IO Image Output",
    "WorkflowIOVideoOutput": "Workflow IO Video Output",
    "WorkflowIO3DOutput": "Workflow IO 3D Output",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
