"""
Resource Controller for O2IMS Operator

Implements O-RAN O2IMS Inventory Service for querying resources.
Exposes ByoHosts as O-Cloud compute resources.
"""

import kopf
import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# API clients
custom_api = None
core_api = None


def init_clients():
    """Initialize Kubernetes API clients."""
    global custom_api, core_api
    if custom_api is None:
        custom_api = client.CustomObjectsApi()
    if core_api is None:
        core_api = client.CoreV1Api()


def list_resources(
    namespace: str = "default",
    resource_type: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    logger=None
) -> Dict[str, Any]:
    """
    List all O-Cloud resources (ByoHosts).
    
    Implements O2IMS Inventory Service: GET /o2ims-infrastructureInventory/v1/resourcePools/{resourcePoolId}/resources
    
    Args:
        namespace: Namespace to query
        resource_type: Filter by resource type (compute, storage, network)
        labels: Filter by labels
        logger: Logger instance
        
    Returns:
        Dict containing list of resources
    """
    init_clients()
    
    try:
        # Query ByoHosts
        byohosts = custom_api.list_namespaced_custom_object(
            group="infrastructure.cluster.x-k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="byohosts"
        )
        
        resources = []
        for host in byohosts.get("items", []):
            metadata = host.get("metadata", {})
            spec = host.get("spec", {})
            status = host.get("status", {})
            
            # Determine availability
            machine_ref = status.get("machineRef")
            is_available = machine_ref is None
            
            # Build O2IMS resource representation
            resource = {
                "resourceId": metadata.get("name"),
                "resourceTypeId": "compute",
                "resourcePoolId": "byoh-host-pool",
                "globalAssetId": metadata.get("uid"),
                "description": f"BYOH Host: {metadata.get('name')}",
                "extensions": {
                    "osName": status.get("os", {}).get("name", "linux"),
                    "osImage": status.get("os", {}).get("image", "Unknown"),
                    "architecture": status.get("architecture", "amd64"),
                    "k8sVersion": status.get("k8sVersion", "Unknown"),
                },
                "status": "available" if is_available else "in-use",
                "machineRef": machine_ref,
                "labels": metadata.get("labels", {}),
                "createdAt": metadata.get("creationTimestamp"),
                "networkInfo": status.get("network", {})
            }
            
            # Apply filters
            if resource_type and resource["resourceTypeId"] != resource_type:
                continue
                
            if labels:
                host_labels = metadata.get("labels", {})
                if not all(host_labels.get(k) == v for k, v in labels.items()):
                    continue
            
            resources.append(resource)
        
        if logger:
            logger.info(f"Found {len(resources)} resources")
        
        return {
            "status": True,
            "count": len(resources),
            "resources": resources
        }
        
    except ApiException as e:
        if logger:
            logger.error(f"Failed to list resources: {e}")
        return {
            "status": False,
            "error": str(e),
            "resources": []
        }


def get_resource(
    name: str,
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Get a specific O-Cloud resource (ByoHost).
    
    Implements O2IMS Inventory Service: GET /o2ims-infrastructureInventory/v1/resourcePools/{resourcePoolId}/resources/{resourceId}
    
    Args:
        name: Resource name (ByoHost name)
        namespace: Namespace
        logger: Logger instance
        
    Returns:
        Dict containing resource details
    """
    init_clients()
    
    try:
        host = custom_api.get_namespaced_custom_object(
            group="infrastructure.cluster.x-k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="byohosts",
            name=name
        )
        
        metadata = host.get("metadata", {})
        status = host.get("status", {})
        
        machine_ref = status.get("machineRef")
        is_available = machine_ref is None
        
        resource = {
            "resourceId": metadata.get("name"),
            "resourceTypeId": "compute",
            "resourcePoolId": "byoh-host-pool",
            "globalAssetId": metadata.get("uid"),
            "description": f"BYOH Host: {metadata.get('name')}",
            "extensions": {
                "osName": status.get("os", {}).get("name", "linux"),
                "osImage": status.get("os", {}).get("image", "Unknown"),
                "architecture": status.get("architecture", "amd64"),
                "k8sVersion": status.get("k8sVersion", "Unknown"),
            },
            "status": "available" if is_available else "in-use",
            "machineRef": machine_ref,
            "labels": metadata.get("labels", {}),
            "createdAt": metadata.get("creationTimestamp"),
            "networkInfo": status.get("network", {})
        }
        
        return {
            "status": True,
            "resource": resource
        }
        
    except ApiException as e:
        if e.status == 404:
            return {
                "status": False,
                "error": f"Resource '{name}' not found"
            }
        if logger:
            logger.error(f"Failed to get resource: {e}")
        return {
            "status": False,
            "error": str(e)
        }


def get_available_resources(
    namespace: str = "default",
    count: Optional[int] = None,
    logger=None
) -> Dict[str, Any]:
    """
    Get available (unassigned) resources.
    
    Args:
        namespace: Namespace to query
        count: Optional - return only if at least this many available
        logger: Logger instance
        
    Returns:
        Dict containing available resources
    """
    result = list_resources(namespace=namespace, logger=logger)
    
    if not result.get("status"):
        return result
    
    available = [r for r in result["resources"] if r["status"] == "available"]
    
    if count and len(available) < count:
        return {
            "status": False,
            "error": f"Insufficient resources. Need {count}, found {len(available)} available.",
            "available": available,
            "count": len(available)
        }
    
    return {
        "status": True,
        "count": len(available),
        "resources": available
    }


def check_host_availability(
    host_names: List[str],
    namespace: str = "default",
    logger=None
) -> Dict[str, Any]:
    """
    Check if specific hosts are available.
    
    Args:
        host_names: List of host names to check
        namespace: Namespace
        logger: Logger instance
        
    Returns:
        Dict with availability status for each host
    """
    init_clients()
    
    results = {
        "status": True,
        "all_available": True,
        "hosts": {}
    }
    
    for name in host_names:
        resource = get_resource(name, namespace, logger)
        
        if not resource.get("status"):
            results["hosts"][name] = {
                "exists": False,
                "available": False,
                "error": resource.get("error", "Not found")
            }
            results["all_available"] = False
            results["status"] = False
        else:
            is_available = resource["resource"]["status"] == "available"
            results["hosts"][name] = {
                "exists": True,
                "available": is_available,
                "machineRef": resource["resource"].get("machineRef")
            }
            if not is_available:
                results["all_available"] = False
    
    return results


# Kopf handler for O2IMS resource query endpoint
@kopf.on.field('o2ims.provisioning.oran.org', 'v1alpha1', 'provisioningrequests', field='metadata.annotations')
def handle_resource_query(annotations, name, namespace, logger, **kwargs):
    """
    Handle resource query requests via annotations.
    
    Usage:
        kubectl annotate provisioningrequest <name> o2ims.oran.org/query-resources="true"
    """
    if annotations and annotations.get("o2ims.oran.org/query-resources") == "true":
        result = list_resources(namespace=namespace, logger=logger)
        logger.info(f"Resource query result: {result}")
        return result
