"""
Kubernetes API Utilities for O2IMS Operator

Provides functions for interacting with the Kubernetes API,
including CAPI cluster resources and status updates.
"""

import os
import logging
from typing import Dict, Any, Optional, List
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# API group constants
O2IMS_API_GROUP = "o2ims.provisioning.oran.org"
O2IMS_API_VERSION = "v1alpha1"
CAPI_CLUSTER_GROUP = "cluster.x-k8s.io"
CAPI_CLUSTER_VERSION = "v1beta1"
BYOH_INFRA_GROUP = "infrastructure.cluster.x-k8s.io"
BYOH_INFRA_VERSION = "v1beta1"

# Initialize Kubernetes client
def init_k8s_client():
    """Initialize Kubernetes client from in-cluster config or kubeconfig."""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded kubeconfig from default location")


def get_dynamic_client():
    """Get Kubernetes dynamic client."""
    return client.ApiClient()


def get_custom_objects_api() -> client.CustomObjectsApi:
    """Get CustomObjectsApi instance."""
    return client.CustomObjectsApi()


def get_core_api() -> client.CoreV1Api:
    """Get CoreV1Api instance."""
    return client.CoreV1Api()


# ProvisioningRequest operations
def get_provisioning_request(
    name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Get a ProvisioningRequest by name.
    
    Returns:
        dict with 'status' (bool) and 'body' (resource dict)
    """
    api = get_custom_objects_api()
    try:
        result = api.get_namespaced_custom_object(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=namespace,
            plural="provisioningrequests",
            name=name
        )
        return {"status": True, "body": result}
    except ApiException as e:
        if logger:
            logger.error(f"Failed to get ProvisioningRequest {name}: {e}")
        return {"status": False, "body": None, "error": str(e)}


def update_provisioning_request_status(
    name: str,
    namespace: str,
    status_update: Dict[str, Any],
    logger=None
) -> Dict[str, Any]:
    """
    Update the status of a ProvisioningRequest.
    
    Args:
        name: Name of the ProvisioningRequest
        namespace: Namespace
        status_update: Status fields to update
        logger: Logger instance
    
    Returns:
        dict with 'status' (bool) and 'body' (updated resource)
    """
    api = get_custom_objects_api()
    try:
        # First get the current resource
        current = api.get_namespaced_custom_object(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=namespace,
            plural="provisioningrequests",
            name=name
        )
        
        # Update status
        if "status" not in current:
            current["status"] = {}
        current["status"].update(status_update)
        
        # Patch the status subresource
        result = api.patch_namespaced_custom_object_status(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=namespace,
            plural="provisioningrequests",
            name=name,
            body=current
        )
        return {"status": True, "body": result}
    except ApiException as e:
        if logger:
            logger.error(f"Failed to update ProvisioningRequest status: {e}")
        return {"status": False, "error": str(e)}


# CAPI Cluster operations
def get_capi_cluster(
    name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Get a CAPI Cluster by name.
    
    Returns:
        dict with 'status' (bool) and 'body' (resource dict)
    """
    api = get_custom_objects_api()
    try:
        result = api.get_namespaced_custom_object(
            group=CAPI_CLUSTER_GROUP,
            version=CAPI_CLUSTER_VERSION,
            namespace=namespace,
            plural="clusters",
            name=name
        )
        return {"status": True, "body": result}
    except ApiException as e:
        if logger:
            logger.debug(f"Cluster {name} not found or error: {e}")
        return {"status": False, "body": None, "error": str(e)}


def apply_k8s_resource(
    resource: Dict[str, Any],
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Apply a Kubernetes resource (create or update).
    
    Args:
        resource: Kubernetes resource dict
        namespace: Target namespace
        logger: Logger instance
    
    Returns:
        dict with 'status' (bool) and 'body' (created/updated resource)
    """
    api = get_custom_objects_api()
    
    api_version = resource.get("apiVersion", "")
    kind = resource.get("kind", "")
    name = resource.get("metadata", {}).get("name", "")
    resource_namespace = resource.get("metadata", {}).get("namespace", namespace)
    
    # Parse API group and version
    if "/" in api_version:
        group, version = api_version.split("/")
    else:
        group = ""
        version = api_version
    
    # Map kind to plural
    plural = _kind_to_plural(kind)
    
    try:
        if group:
            # Custom resource
            try:
                # Try to get existing resource
                existing = api.get_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=resource_namespace,
                    plural=plural,
                    name=name
                )
                # Update existing
                resource["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
                result = api.replace_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=resource_namespace,
                    plural=plural,
                    name=name,
                    body=resource
                )
                if logger:
                    logger.info(f"Updated {kind}/{name}")
            except ApiException as e:
                if e.status == 404:
                    # Create new
                    result = api.create_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=resource_namespace,
                        plural=plural,
                        body=resource
                    )
                    if logger:
                        logger.info(f"Created {kind}/{name}")
                else:
                    raise
        else:
            # Core API resource - shouldn't happen for CAPI resources
            if logger:
                logger.warning(f"Core API resource handling not implemented for {kind}")
            return {"status": False, "error": "Core API not supported"}
        
        return {"status": True, "body": result}
    
    except ApiException as e:
        if logger:
            logger.error(f"Failed to apply {kind}/{name}: {e}")
        return {"status": False, "error": str(e)}


def _kind_to_plural(kind: str) -> str:
    """Convert Kubernetes kind to plural form."""
    kind_plural_map = {
        "Cluster": "clusters",
        "ByoCluster": "byoclusters",
        "ByoHost": "byohosts",
        "ByoMachine": "byomachines",
        "ByoMachineTemplate": "byomachinetemplates",
        "KubeadmControlPlane": "kubeadmcontrolplanes",
        "KubeadmConfigTemplate": "kubeadmconfigtemplates",
        "MachineDeployment": "machinedeployments",
        "Machine": "machines",
        "MachineSet": "machinesets",
        "K8sInstallerConfigTemplate": "k8sinstallerconfigtemplates",
        "ProvisioningRequest": "provisioningrequests",
    }
    return kind_plural_map.get(kind, kind.lower() + "s")


def delete_cluster_resources(
    cluster_name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Delete all resources associated with a cluster.
    
    This deletes the Cluster object which triggers CAPI to clean up
    all associated resources (machines, etc.)
    """
    api = get_custom_objects_api()
    try:
        api.delete_namespaced_custom_object(
            group=CAPI_CLUSTER_GROUP,
            version=CAPI_CLUSTER_VERSION,
            namespace=namespace,
            plural="clusters",
            name=cluster_name
        )
        if logger:
            logger.info(f"Deleted cluster {cluster_name}")
        return {"status": True}
    except ApiException as e:
        if logger:
            logger.error(f"Failed to delete cluster {cluster_name}: {e}")
        return {"status": False, "error": str(e)}


def get_byohosts(
    namespace: str = "default",
    labels: Optional[Dict[str, str]] = None,
    logger=None
) -> List[Dict[str, Any]]:
    """
    Get list of ByoHosts, optionally filtered by labels.
    """
    api = get_custom_objects_api()
    try:
        label_selector = ",".join([f"{k}={v}" for k, v in (labels or {}).items()])
        result = api.list_namespaced_custom_object(
            group=BYOH_INFRA_GROUP,
            version=BYOH_INFRA_VERSION,
            namespace=namespace,
            plural="byohosts",
            label_selector=label_selector if label_selector else None
        )
        return result.get("items", [])
    except ApiException as e:
        if logger:
            logger.error(f"Failed to list ByoHosts: {e}")
        return []


def get_byohost(
    name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Get a single ByoHost by name.

    Returns:
        dict with 'status' (bool) and 'body' (resource dict)
    """
    api = get_custom_objects_api()
    try:
        result = api.get_namespaced_custom_object(
            group=BYOH_INFRA_GROUP,
            version=BYOH_INFRA_VERSION,
            namespace=namespace,
            plural="byohosts",
            name=name
        )
        return {"status": True, "body": result}
    except ApiException as e:
        if e.status == 404:
            return {"status": False, "body": None, "not_found": True}
        if logger:
            logger.error(f"Failed to get ByoHost {name}: {e}")
        return {"status": False, "body": None, "error": str(e)}


def label_byohost(
    name: str,
    labels: Dict[str, str],
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Add labels to a ByoHost.
    """
    api = get_custom_objects_api()
    try:
        # Get current host
        host = api.get_namespaced_custom_object(
            group=BYOH_INFRA_GROUP,
            version=BYOH_INFRA_VERSION,
            namespace=namespace,
            plural="byohosts",
            name=name
        )
        
        # Update labels
        if "metadata" not in host:
            host["metadata"] = {}
        if "labels" not in host["metadata"]:
            host["metadata"]["labels"] = {}
        host["metadata"]["labels"].update(labels)
        
        # Patch
        result = api.patch_namespaced_custom_object(
            group=BYOH_INFRA_GROUP,
            version=BYOH_INFRA_VERSION,
            namespace=namespace,
            plural="byohosts",
            name=name,
            body=host
        )
        if logger:
            logger.info(f"Labeled ByoHost {name} with {labels}")
        return {"status": True, "body": result}
    except ApiException as e:
        if logger:
            logger.error(f"Failed to label ByoHost {name}: {e}")
        return {"status": False, "error": str(e)}
