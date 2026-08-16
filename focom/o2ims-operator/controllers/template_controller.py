"""
Template Controller for O2IMS Operator

Manages ClusterTemplate resources and provides template query/validation.
"""

import kopf
import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Constants
TEMPLATE_GROUP = "o2ims.provisioning.oran.org"
TEMPLATE_VERSION = "v1alpha1"
TEMPLATE_PLURAL = "clustertemplates"

# API client
custom_api = None


def init_client():
    """Initialize Kubernetes API client."""
    global custom_api
    if custom_api is None:
        custom_api = client.CustomObjectsApi()


def list_templates(
    namespace: str = "default",
    labels: Optional[Dict[str, str]] = None,
    logger=None
) -> Dict[str, Any]:
    """
    List all available ClusterTemplates.
    
    Args:
        namespace: Namespace to query
        labels: Optional label filter
        logger: Logger instance
        
    Returns:
        Dict containing list of templates
    """
    init_client()
    
    try:
        label_selector = ",".join([f"{k}={v}" for k, v in labels.items()]) if labels else None
        
        templates = custom_api.list_namespaced_custom_object(
            group=TEMPLATE_GROUP,
            version=TEMPLATE_VERSION,
            namespace=namespace,
            plural=TEMPLATE_PLURAL,
            label_selector=label_selector
        )
        
        result = []
        for tpl in templates.get("items", []):
            metadata = tpl.get("metadata", {})
            spec = tpl.get("spec", {})
            status = tpl.get("status", {})
            
            result.append({
                "templateId": metadata.get("name"),
                "name": spec.get("name"),
                "version": spec.get("version"),
                "description": spec.get("description", ""),
                "provisioner": spec.get("provisioner", "byoh"),
                "k8sVersions": spec.get("k8sVersions", []),
                "defaultK8sVersion": spec.get("defaultK8sVersion", "v1.32.0"),
                "nodeRequirements": spec.get("nodeRequirements", {}),
                "networking": spec.get("networking", {}),
                "labels": metadata.get("labels", {}),
                "phase": status.get("phase", "Active"),
                "usageCount": status.get("usageCount", 0)
            })
        
        if logger:
            logger.info(f"Found {len(result)} templates")
        
        return {
            "status": True,
            "count": len(result),
            "templates": result
        }
        
    except ApiException as e:
        if logger:
            logger.error(f"Failed to list templates: {e}")
        return {
            "status": False,
            "error": str(e),
            "templates": []
        }


def get_template(
    name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Get a specific ClusterTemplate.
    
    Args:
        name: Template name
        namespace: Namespace
        logger: Logger instance
        
    Returns:
        Dict containing template details
    """
    init_client()
    
    try:
        tpl = custom_api.get_namespaced_custom_object(
            group=TEMPLATE_GROUP,
            version=TEMPLATE_VERSION,
            namespace=namespace,
            plural=TEMPLATE_PLURAL,
            name=name
        )
        
        metadata = tpl.get("metadata", {})
        spec = tpl.get("spec", {})
        status = tpl.get("status", {})
        
        template = {
            "templateId": metadata.get("name"),
            "name": spec.get("name"),
            "version": spec.get("version"),
            "description": spec.get("description", ""),
            "provisioner": spec.get("provisioner", "byoh"),
            "k8sVersions": spec.get("k8sVersions", []),
            "defaultK8sVersion": spec.get("defaultK8sVersion", "v1.32.0"),
            "nodeRequirements": spec.get("nodeRequirements", {}),
            "networking": spec.get("networking", {}),
            "labels": metadata.get("labels", {}),
            "phase": status.get("phase", "Active"),
            "usageCount": status.get("usageCount", 0)
        }
        
        return {
            "status": True,
            "template": template
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": False,
                "error": f"Template '{name}' not found"
            }
        if logger:
            logger.error(f"Failed to get template: {e}")
        return {
            "status": False,
            "error": str(e)
        }


def validate_against_template(
    template_name: str,
    k8s_version: str,
    master_count: int,
    worker_count: int,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Validate a provisioning request against a ClusterTemplate.
    
    Args:
        template_name: Name of the ClusterTemplate
        k8s_version: Requested Kubernetes version
        master_count: Number of master nodes
        worker_count: Number of worker nodes
        namespace: Namespace
        logger: Logger instance
        
    Returns:
        Dict with validation results
    """
    # Get template
    result = get_template(template_name, namespace, logger)
    
    if not result.get("status"):
        return {
            "valid": False,
            "errors": [result.get("error", f"Template '{template_name}' not found")]
        }
    
    template = result["template"]
    errors = []
    warnings = []
    
    # Check template status
    if template.get("phase") == "Deprecated":
        warnings.append(f"Template '{template_name}' is deprecated")
    elif template.get("phase") == "Invalid":
        errors.append(f"Template '{template_name}' is invalid")
    
    # Check K8s version
    allowed_versions = template.get("k8sVersions", [])
    if k8s_version and allowed_versions and k8s_version not in allowed_versions:
        errors.append(
            f"Kubernetes version '{k8s_version}' not supported. "
            f"Allowed versions: {', '.join(allowed_versions)}"
        )
    
    # Check node counts (minimum only, no maximum limits)
    node_req = template.get("nodeRequirements", {})
    
    min_masters = node_req.get("minMasters", 1)
    if master_count < min_masters:
        errors.append(f"Minimum {min_masters} master node(s) required, got {master_count}")
    
    # Master count must be odd for etcd quorum
    if master_count > 0 and master_count % 2 == 0:
        errors.append(f"Master count must be odd (1, 3, 5, etc.) for etcd quorum, got {master_count}")
    
    min_workers = node_req.get("minWorkers", 0)
    if worker_count < min_workers:
        errors.append(f"Minimum {min_workers} worker node(s) required, got {worker_count}")
    
    is_valid = len(errors) == 0
    
    return {
        "valid": is_valid,
        "template": template_name,
        "errors": errors,
        "warnings": warnings,
        "templateDetails": {
            "name": template.get("name"),
            "version": template.get("version"),
            "defaultK8sVersion": template.get("defaultK8sVersion")
        }
    }


def increment_template_usage(
    template_name: str,
    namespace: str = "default",
    logger=None
) -> bool:
    """
    Increment the usage count of a template.
    
    Args:
        template_name: Template name
        namespace: Namespace
        logger: Logger instance
        
    Returns:
        True if successful
    """
    init_client()
    
    try:
        # Get current template
        tpl = custom_api.get_namespaced_custom_object(
            group=TEMPLATE_GROUP,
            version=TEMPLATE_VERSION,
            namespace=namespace,
            plural=TEMPLATE_PLURAL,
            name=template_name
        )
        
        # Update status
        current_count = tpl.get("status", {}).get("usageCount", 0)
        
        patch = {
            "status": {
                "usageCount": current_count + 1,
                "lastUsed": client.ApiClient().sanitize_for_serialization(
                    client.V1Time()
                )
            }
        }
        
        custom_api.patch_namespaced_custom_object_status(
            group=TEMPLATE_GROUP,
            version=TEMPLATE_VERSION,
            namespace=namespace,
            plural=TEMPLATE_PLURAL,
            name=template_name,
            body=patch
        )
        
        if logger:
            logger.info(f"Incremented usage count for template '{template_name}'")
        
        return True
        
    except ApiException as e:
        if logger:
            logger.warning(f"Failed to increment template usage: {e}")
        return False


# Kopf handler for ClusterTemplate lifecycle
@kopf.on.create(TEMPLATE_GROUP, TEMPLATE_VERSION, TEMPLATE_PLURAL)
def handle_template_create(spec, name, namespace, logger, **kwargs):
    """Handle ClusterTemplate creation."""
    logger.info(f"ClusterTemplate created: {name}")
    
    # Validate template
    k8s_versions = spec.get("k8sVersions", [])
    default_version = spec.get("defaultK8sVersion", "v1.32.0")
    
    if k8s_versions and default_version not in k8s_versions:
        logger.warning(f"Default K8s version {default_version} not in allowed versions")
    
    return {"phase": "Active"}


@kopf.on.delete(TEMPLATE_GROUP, TEMPLATE_VERSION, TEMPLATE_PLURAL)
def handle_template_delete(name, namespace, logger, **kwargs):
    """Handle ClusterTemplate deletion."""
    logger.info(f"ClusterTemplate deleted: {name}")
