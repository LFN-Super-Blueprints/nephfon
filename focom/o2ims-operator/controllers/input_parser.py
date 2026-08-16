"""
Input Parser for O2IMS Operator

Parses input.json to get cluster configurations and resolve host_ids to full host details.
Supports the simplified cluster provisioning approach.
"""

import json
import logging
import os
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Default input file path (inside container)
DEFAULT_INPUT_PATH = "/workspace/input.json"

# Cached config
_cached_config = None


def load_input_config(path: str = None) -> Dict[str, Any]:
    """
    Load and parse input.json.
    
    Args:
        path: Path to input.json (default: /workspace/input.json)
        
    Returns:
        Parsed config dict
    """
    global _cached_config
    
    if path is None:
        path = os.environ.get("INPUT_JSON_PATH", DEFAULT_INPUT_PATH)
    
    # Use cache if available
    if _cached_config is not None:
        return _cached_config
    
    try:
        with open(path, 'r') as f:
            _cached_config = json.load(f)
        logger.info(f"Loaded input.json from {path}")
        return _cached_config
    except FileNotFoundError:
        logger.error(f"input.json not found at {path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        return {}


def reload_config(path: str = None) -> Dict[str, Any]:
    """Force reload of input.json (clears cache)."""
    global _cached_config
    _cached_config = None
    return load_input_config(path)


def get_host_by_id(host_id: int, config: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """
    Get host details by host_id.
    
    Args:
        host_id: The host ID to look up
        config: Optional config dict (loads from file if not provided)
        
    Returns:
        Host dict or None if not found
    """
    if config is None:
        config = load_input_config()
    
    hosts = config.get("hosts", [])
    for host in hosts:
        if host.get("host_id") == host_id:
            return host
    
    return None


def get_cluster_config(cluster_name: str, config: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """
    Get cluster config by name, resolving host_ids to full host details.
    
    Args:
        cluster_name: Name of the cluster
        config: Optional config dict
        
    Returns:
        Cluster config with resolved hosts, or None if not found
    """
    if config is None:
        config = load_input_config()
    
    clusters = config.get("clusters", [])
    k8s_version = config.get("k8s_version", "1.32.0")
    
    for cluster in clusters:
        if cluster.get("cluster_name") == cluster_name:
            # Resolve master host_ids
            masters = []
            for m in cluster.get("cluster_masters", []):
                host_id = m.get("host_id")
                host = get_host_by_id(host_id, config)
                if host:
                    masters.append({
                        "hostId": host_id,
                        "hostName": host.get("host_name"),
                        "hostIp": host.get("host_ip"),
                        "hostUser": host.get("host_user")
                    })
            
            # Resolve worker host_ids
            workers = []
            for w in cluster.get("cluster_workers", []):
                host_id = w.get("host_id")
                host = get_host_by_id(host_id, config)
                if host:
                    workers.append({
                        "hostId": host_id,
                        "hostName": host.get("host_name"),
                        "hostIp": host.get("host_ip"),
                        "hostUser": host.get("host_user")
                    })
            
            return {
                "clusterName": cluster_name,
                "k8sVersion": f"v{k8s_version}" if not k8s_version.startswith("v") else k8s_version,
                "clusterProvisioner": "byoh",
                "clusterType": cluster.get("cluster_type", ""),
                "hosts": {
                    "masters": masters,
                    "workers": workers
                },
                "podCidr": cluster.get("pod_cidr", "10.244.0.0/16"),
                "serviceCidr": cluster.get("service_cidr", "10.96.0.0/12"),
                "masterCount": len(masters),
                "workerCount": len(workers),
                "totalHosts": len(masters) + len(workers)
            }
    
    return None


def list_clusters(config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    List all clusters defined in input.json.
    
    Args:
        config: Optional config dict
        
    Returns:
        List of cluster summaries
    """
    if config is None:
        config = load_input_config()
    
    clusters = config.get("clusters", [])
    result = []
    
    for cluster in clusters:
        name = cluster.get("cluster_name")
        masters = len(cluster.get("cluster_masters", []))
        workers = len(cluster.get("cluster_workers", []))
        
        result.append({
            "name": name,
            "masters": masters,
            "workers": workers,
            "total": masters + workers
        })
    
    return result


def validate_cluster(cluster_name: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Validate a cluster configuration.
    
    Checks:
    - Cluster exists
    - All host_ids exist
    - Master count is odd (for etcd quorum)
    - No duplicate host_ids across roles
    - K8s version in supported range
    
    Args:
        cluster_name: Name of the cluster to validate
        config: Optional config dict
        
    Returns:
        Dict with valid: bool, errors: List[str], warnings: List[str]
    """
    if config is None:
        config = load_input_config()
    
    errors = []
    warnings = []
    
    # Check cluster exists
    cluster_config = get_cluster_config(cluster_name, config)
    if not cluster_config:
        return {
            "valid": False,
            "errors": [f"Cluster '{cluster_name}' not found in input.json"],
            "warnings": []
        }
    
    # Check K8s version
    k8s_version = cluster_config.get("k8sVersion", "v1.32.0")
    supported_versions = [f"v1.{v}.0" for v in range(26, 35)]
    if k8s_version not in supported_versions:
        errors.append(f"K8s version '{k8s_version}' not supported. Allowed: v1.26.0 - v1.34.0")
    
    # Check master count is odd
    master_count = cluster_config.get("masterCount", 0)
    if master_count == 0:
        errors.append("At least 1 master node is required")
    elif master_count % 2 == 0:
        errors.append(f"Master count must be odd (1, 3, 5, etc.) for etcd quorum, got {master_count}")
    
    # Check for duplicate hosts
    all_host_ids = []
    for m in cluster_config.get("hosts", {}).get("masters", []):
        all_host_ids.append(m.get("hostId"))
    for w in cluster_config.get("hosts", {}).get("workers", []):
        all_host_ids.append(w.get("hostId"))
    
    if len(all_host_ids) != len(set(all_host_ids)):
        errors.append("Duplicate host_ids detected in cluster configuration")
    
    # Check hosts were resolved (exist in hosts array)
    clusters = config.get("clusters", [])
    for cluster in clusters:
        if cluster.get("cluster_name") == cluster_name:
            for m in cluster.get("cluster_masters", []):
                if not get_host_by_id(m.get("host_id"), config):
                    errors.append(f"Master host_id {m.get('host_id')} not found in hosts array")
            for w in cluster.get("cluster_workers", []):
                if not get_host_by_id(w.get("host_id"), config):
                    errors.append(f"Worker host_id {w.get('host_id')} not found in hosts array")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "cluster": cluster_config
    }


def check_host_conflicts(cluster_name: str, existing_clusters: List[str] = None, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Check if cluster's hosts conflict with other clusters.
    
    Args:
        cluster_name: Cluster to check
        existing_clusters: List of already provisioned cluster names
        config: Optional config dict
        
    Returns:
        Dict with conflicts info
    """
    if config is None:
        config = load_input_config()
    
    if existing_clusters is None:
        existing_clusters = []
    
    cluster_config = get_cluster_config(cluster_name, config)
    if not cluster_config:
        return {"conflicts": False, "message": "Cluster not found"}
    
    # Get this cluster's host_ids
    this_cluster_hosts = set()
    for m in cluster_config.get("hosts", {}).get("masters", []):
        this_cluster_hosts.add(m.get("hostId"))
    for w in cluster_config.get("hosts", {}).get("workers", []):
        this_cluster_hosts.add(w.get("hostId"))
    
    # Check against other clusters in input.json
    conflicts = []
    clusters = config.get("clusters", [])
    
    for cluster in clusters:
        other_name = cluster.get("cluster_name")
        if other_name == cluster_name:
            continue
        if existing_clusters and other_name not in existing_clusters:
            continue
        
        other_hosts = set()
        for m in cluster.get("cluster_masters", []):
            other_hosts.add(m.get("host_id"))
        for w in cluster.get("cluster_workers", []):
            other_hosts.add(w.get("host_id"))
        
        overlap = this_cluster_hosts & other_hosts
        if overlap:
            conflicts.append({
                "cluster": other_name,
                "shared_hosts": list(overlap)
            })
    
    return {
        "conflicts": len(conflicts) > 0,
        "details": conflicts
    }


def get_all_hosts_for_ansible(config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """
    Get all hosts in format needed for Ansible inventory.
    
    Returns:
        List of host dicts with ansible-compatible fields
    """
    if config is None:
        config = load_input_config()
    
    hosts = config.get("hosts", [])
    result = []
    
    for host in hosts:
        result.append({
            "host_id": host.get("host_id"),
            "host_name": host.get("host_name"),
            "host_ip": host.get("host_ip"),
            "host_user": host.get("host_user"),
            "host_pwd": host.get("host_pwd", "")
        })
    
    return result
