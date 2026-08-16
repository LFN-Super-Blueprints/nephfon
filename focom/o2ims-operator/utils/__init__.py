"""
Utility functions and constants for O2IMS Operator
"""

from datetime import datetime

# Time format for status updates
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Provisioning states
class ProvisioningState:
    PENDING = "pending"
    PROGRESSING = "progressing"
    FULFILLED = "fulfilled"
    FAILED = "failed"
    DELETING = "deleting"


def get_current_time() -> str:
    """Get current time in ISO format."""
    return datetime.utcnow().strftime(TIME_FORMAT)


def check_o2ims_provisioning_request(name: str, namespace: str, logger=None):
    """Check status of a provisioning request."""
    from .k8s_utils import get_provisioning_request
    return get_provisioning_request(name, namespace, logger)
