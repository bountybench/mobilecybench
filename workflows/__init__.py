"""Workflow classes for different evaluation modes."""

from workflows.base import Workflow
from workflows.detection import DetectionWorkflow
from workflows.exploit import ExploitWorkflow
from workflows.redteam import RedTeamWorkflow

__all__ = [
    "Workflow",
    "DetectionWorkflow",
    "ExploitWorkflow",
    "RedTeamWorkflow",
]
