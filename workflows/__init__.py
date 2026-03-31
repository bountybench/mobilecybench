"""Workflow classes for different evaluation modes."""

from workflows.base import Workflow
from workflows.detection import DetectionWorkflow
from workflows.discovery import DiscoveryWorkflow
from workflows.exploit import ExploitWorkflow
from workflows.malicious_apk import MaliciousApkWorkflow
from workflows.unified import UnifiedWorkflow

__all__ = [
    "Workflow",
    "DetectionWorkflow",
    "DiscoveryWorkflow",
    "ExploitWorkflow",
    "MaliciousApkWorkflow",
    "UnifiedWorkflow",
]
