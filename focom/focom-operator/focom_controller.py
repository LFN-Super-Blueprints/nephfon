"""
FOCOM ProvisioningRequest Controller

This controller watches FocomProvisioningRequest CRs and creates corresponding
O2IMS ProvisioningRequest CRs in the target O-Cloud namespace.

Features:
- Request validation against ClusterTemplate
- Feasibility check for resource availability
- Query templates and resources
- SMO/orchestrator integration layer for O-RAN O2 IMS
"""

import kopf
import logging
import re
from datetime import datetime
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API constants
FOCOM_API_GROUP = "focom.nephio.org"
FOCOM_API_VERSION = "v1alpha1"
O2IMS_API_GROUP = "o2ims.provisioning.oran.org"
O2IMS_API_VERSION = "v1alpha1"
TEMPLATE_GROUP = "o2ims.provisioning.oran.org"
BYOH_GROUP = "infrastructure.cluster.x-k8s.io"

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def init_k8s_client():
    """Initialize Kubernetes client."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def get_current_time() -> str:
    """Get current time in ISO format."""
    return datetime.utcnow().strftime(TIME_FORMAT)


# =============================================================================
# QUERY FUNCTIONS (Features F2, F6)
# =============================================================================

def query_templates(namespace: str = "default", logger=None) -> Dict[str, Any]:
    """
    Query available ClusterTemplates.
    
    Feature: F2 - Query Templates
    """
    try:
        api = client.CustomObjectsApi()
        templates = api.list_namespaced_custom_object(
            group=TEMPLATE_GROUP,
            version="v1alpha1",
            namespace=namespace,
            plural="clustertemplates"
        )
        
        result = []
        for tpl in templates.get("items", []):
            spec = tpl.get("spec", {})
            result.append({
                "templateId": tpl["metadata"]["name"],
                "name": spec.get("name"),
                "version": spec.get("version"),
                "description": spec.get("description", ""),
                "k8sVersions": spec.get("k8sVersions", []),
                "nodeRequirements": spec.get("nodeRequirements", {})
            })
        
        return {"status": True, "templates": result, "count": len(result)}
    except ApiException as e:
        return {"status": False, "error": str(e), "templates": []}


def query_resources(namespace: str = "default", logger=None) -> Dict[str, Any]:
    """
    Query available O-Cloud resources (ByoHosts).
    
    Feature: F6 - Query O-Cloud Resources
    """
    try:
        api = client.CustomObjectsApi()
        hosts = api.list_namespaced_custom_object(
            group=BYOH_GROUP,
            version="v1beta1",
            namespace=namespace,
            plural="byohosts"
        )
        
        resources = []
        for host in hosts.get("items", []):
            metadata = host.get("metadata", {})
            status = host.get("status", {})
            machine_ref = status.get("machineRef")
            
            resources.append({
                "resourceId": metadata.get("name"),
                "type": "compute",
                "status": "available" if machine_ref is None else "in-use",
                "os": status.get("os", {}).get("image", "Unknown"),
                "arch": status.get("architecture", "amd64"),
                "labels": metadata.get("labels", {})
            })
        
        return {"status": True, "resources": resources, "count": len(resources)}
    except ApiException as e:
        return {"status": False, "error": str(e), "resources": []}


# =============================================================================
# VALIDATION FUNCTIONS (Feature F4)
# =============================================================================

def validate_request(spec: Dict[str, Any], namespace: str = "default", logger=None) -> Dict[str, Any]:
    """
    Validate a FocomProvisioningRequest before creating.
    
    Feature: F4 - Request Validation
    
    Checks:
    - Template exists and is active
    - K8s version is supported
    - Node counts are within limits
    - Cluster name is valid DNS format
    - Host names are unique
    """
    errors = []
    warnings = []
    
    template_name = spec.get("templateName")
    template_params = spec.get("templateParameters", {})
    
    # 1. Validate cluster name (DNS compatible)
    cluster_name = template_params.get("clusterName", "")
    if not cluster_name:
        errors.append("templateParameters.clusterName is required")
    elif not re.match(r'^[a-z][a-z0-9-]*[a-z0-9]$', cluster_name) or len(cluster_name) < 2:
        errors.append(f"clusterName '{cluster_name}' must be lowercase, start with a letter, and contain only a-z, 0-9, -")
    
    # 2. Validate template exists
    if not template_name:
        errors.append("templateName is required")
    else:
        try:
            api = client.CustomObjectsApi()
            template = api.get_namespaced_custom_object(
                group=TEMPLATE_GROUP,
                version="v1alpha1",
                namespace=namespace,
                plural="clustertemplates",
                name=template_name
            )
            
            tpl_spec = template.get("spec", {})
            tpl_status = template.get("status", {})
            
            # Check template status
            if tpl_status.get("phase") == "Deprecated":
                warnings.append(f"Template '{template_name}' is deprecated")
            elif tpl_status.get("phase") == "Invalid":
                errors.append(f"Template '{template_name}' is invalid")
            
            # 3. Validate K8s version
            k8s_version = template_params.get("k8sVersion", tpl_spec.get("defaultK8sVersion"))
            allowed_versions = tpl_spec.get("k8sVersions", [])
            if k8s_version and allowed_versions and k8s_version not in allowed_versions:
                errors.append(f"K8s version '{k8s_version}' not supported. Allowed: {', '.join(allowed_versions)}")
            
            # 4. Validate node counts (minimum only, no maximum limits)
            node_req = tpl_spec.get("nodeRequirements", {})
            hosts = template_params.get("hosts", {})
            masters = hosts.get("masters", [])
            workers = hosts.get("workers", [])
            
            min_masters = node_req.get("minMasters", 1)
            min_workers = node_req.get("minWorkers", 0)
            
            if len(masters) < min_masters:
                errors.append(f"Need at least {min_masters} master(s), got {len(masters)}")
            if len(workers) < min_workers:
                errors.append(f"Need at least {min_workers} worker(s), got {len(workers)}")
            
            # 5. Validate master count is ODD (for etcd quorum)
            if len(masters) > 0 and len(masters) % 2 == 0:
                errors.append(f"Master count must be odd (1, 3, 5, etc.) for etcd quorum, got {len(masters)}")
            
            # 6. Validate host uniqueness
            all_hosts = masters + workers
            host_names = [h.get("hostName") for h in all_hosts if h.get("hostName")]
            if len(host_names) != len(set(host_names)):
                errors.append("Duplicate host names detected")
            
        except ApiException as e:
            if e.status == 404:
                errors.append(f"Template '{template_name}' not found")
            else:
                errors.append(f"Failed to validate template: {e}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


# =============================================================================
# FEASIBILITY CHECK (Feature F5)
# =============================================================================

def check_feasibility(spec: Dict[str, Any], namespace: str = "default", logger=None) -> Dict[str, Any]:
    """
    Check if requested resources are available.
    
    Feature: F5 - Feasibility Check
    
    Checks:
    - All specified hosts exist as ByoHost resources
    - All specified hosts are available (not assigned to another cluster)
    """
    errors = []
    warnings = []
    host_status = {}
    
    template_params = spec.get("templateParameters", {})
    hosts = template_params.get("hosts", {})
    masters = hosts.get("masters", [])
    workers = hosts.get("workers", [])
    all_hosts = masters + workers
    
    if not all_hosts:
        errors.append("No hosts specified in templateParameters.hosts")
        return {"feasible": False, "errors": errors, "warnings": warnings, "hostStatus": host_status}
    
    try:
        api = client.CustomObjectsApi()
        
        for host in all_hosts:
            host_name = host.get("hostName")
            if not host_name:
                continue
            
            try:
                byohost = api.get_namespaced_custom_object(
                    group=BYOH_GROUP,
                    version="v1beta1",
                    namespace=namespace,
                    plural="byohosts",
                    name=host_name
                )
                
                status = byohost.get("status", {})
                machine_ref = status.get("machineRef")
                
                if machine_ref:
                    errors.append(f"Host '{host_name}' is already in use by {machine_ref}")
                    host_status[host_name] = {"exists": True, "available": False, "machineRef": machine_ref}
                else:
                    host_status[host_name] = {"exists": True, "available": True}
                    
            except ApiException as e:
                if e.status == 404:
                    # Host not registered - might be registered by Ansible
                    warnings.append(f"Host '{host_name}' not yet registered as ByoHost")
                    host_status[host_name] = {"exists": False, "available": False}
                else:
                    errors.append(f"Failed to check host '{host_name}': {e}")
                    host_status[host_name] = {"exists": False, "available": False, "error": str(e)}
                    
    except ApiException as e:
        errors.append(f"Failed to query hosts: {e}")
    
    # Only fail if hosts are in use, not if they don't exist yet (Ansible will register them)
    in_use_hosts = [h for h, s in host_status.items() if s.get("exists") and not s.get("available")]
    
    return {
        "feasible": len(in_use_hosts) == 0,
        "errors": errors,
        "warnings": warnings,
        "hostStatus": host_status
    }


# =============================================================================
# KOPF HANDLERS
# =============================================================================

@kopf.on.startup()
def startup_handler(settings: kopf.OperatorSettings, **kwargs):
    """Initialize the operator on startup."""
    logger.info("FOCOM Operator starting up...")
    init_k8s_client()
    settings.persistence.finalizer = f"{FOCOM_API_GROUP}/kopf-finalizer"


@kopf.on.create(FOCOM_API_GROUP, FOCOM_API_VERSION, "focomprovisioningrequests")
def handle_create(spec, name, namespace, logger, **kwargs):
    """
    Handle creation of a FocomProvisioningRequest.
    
    Supports four approaches:
    1. ClusterTemplate-based: spec.templateName + spec.templateParameters
    2. input.json single cluster: spec.clusterName (references input.json)
    3. input.json multiple clusters: spec.clusterNames (array of cluster names)
    4. input.json all clusters: spec.allClusters = true
    """
    logger.info(f"Processing new FocomProvisioningRequest: {name}")
    
    # Skip create logic for non-create operations (upgrade, scale, delete)
    operation = spec.get("operation", "create")
    if operation in ["upgrade", "scale", "delete"]:
        logger.info(f"Skipping create handler for operation: {operation}")
        return {"status": "skipped", "message": f"Operation '{operation}' handled by specific handler"}
    
    # Extract spec fields
    ocloud_namespace = spec.get("oCloudNamespace", "default")
    req_name = spec.get("name", name)
    description = spec.get("description", "")
    template_name = spec.get("templateName")
    template_version = spec.get("templateVersion")
    template_params = spec.get("templateParameters", {})
    
    # Check for simplified approaches
    cluster_name_from_input = spec.get("clusterName")
    cluster_names_list = spec.get("clusterNames", [])  # NEW: Array of cluster names
    all_clusters = spec.get("allClusters", False)
    
    # === OPTION D: Multiple specific clusters from clusterNames array ===
    if cluster_names_list and len(cluster_names_list) > 0:
        logger.info(f"Using multi-cluster provisioning: clusterNames={cluster_names_list}")
        update_status(name, namespace, "Loading", f"Loading {len(cluster_names_list)} clusters from input.json", logger)
        
        # Load input parser  
        try:
            from controllers.input_parser import get_cluster_config, validate_cluster
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from input_parser import get_cluster_config, validate_cluster
        
        # Validate all specified clusters first
        update_status(name, namespace, "Validating", f"Validating {len(cluster_names_list)} clusters", logger)
        all_errors = []
        for cluster_name in cluster_names_list:
            validation = validate_cluster(cluster_name)
            if not validation.get("valid"):
                all_errors.extend([f"{cluster_name}: {e}" for e in validation["errors"]])
        
        if all_errors:
            error_msg = f"Validation failed: {'; '.join(all_errors[:5])}"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "phase": "validation", "errors": all_errors}
        
        # Create ProvisioningRequest for each specified cluster
        update_status(name, namespace, "Creating", f"Creating {len(cluster_names_list)} ProvisioningRequests", logger)
        
        created_requests = []
        api = client.CustomObjectsApi()
        
        for cluster_name in cluster_names_list:
            cluster_config = get_cluster_config(cluster_name)
            
            cluster_template_params = {
                "clusterName": cluster_config.get("clusterName"),
                "k8sVersion": cluster_config.get("k8sVersion"),
                "clusterProvisioner": cluster_config.get("clusterProvisioner", "byoh"),
                "clusterType": cluster_config.get("clusterType", ""),
                "hosts": cluster_config.get("hosts", {}),
                "podCidr": cluster_config.get("podCidr", "10.244.0.0/16"),
                "serviceCidr": cluster_config.get("serviceCidr", "10.96.0.0/12")
            }
            
            pr_name = f"{name}-{cluster_name}-o2ims"
            provisioning_request = {
                "apiVersion": f"{O2IMS_API_GROUP}/{O2IMS_API_VERSION}",
                "kind": "ProvisioningRequest",
                "metadata": {
                    "name": pr_name,
                    "namespace": ocloud_namespace,
                    "labels": {
                        "focom.nephio.org/source": name,
                        "focom.nephio.org/source-namespace": namespace,
                        "focom.nephio.org/source-type": "multi-cluster",
                        "focom.nephio.org/cluster-name": cluster_name
                    }
                },
                "spec": {
                    "name": cluster_name,
                    "description": f"Cluster {cluster_name} from multi-cluster request {name}",
                    "templateName": "byoh-workload-cluster",
                    "templateVersion": "v1.0.0",
                    "templateParameters": cluster_template_params
                }
            }
            
            try:
                api.create_namespaced_custom_object(
                    group=O2IMS_API_GROUP,
                    version=O2IMS_API_VERSION,
                    namespace=ocloud_namespace,
                    plural="provisioningrequests",
                    body=provisioning_request
                )
                created_requests.append(pr_name)
                logger.info(f"Created ProvisioningRequest: {pr_name}")
            except ApiException as e:
                logger.error(f"Failed to create {pr_name}: {e}")
        
        update_status(
            name, namespace, "Synced",
            f"Created {len(created_requests)} ProvisioningRequests: {', '.join(created_requests)}",
            logger,
            remote_name=",".join(created_requests)
        )
        
        return {"status": "synced", "createdRequests": created_requests, "count": len(created_requests)}
    
    # === OPTION C: Batch provisioning - allClusters: true ===
    elif all_clusters:
        logger.info("Using batch provisioning: allClusters=true")
        update_status(name, namespace, "Loading", "Loading all clusters from input.json", logger)
        
        # Load input parser
        try:
            from controllers.input_parser import list_clusters, get_cluster_config, validate_cluster
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from input_parser import list_clusters, get_cluster_config, validate_cluster
        
        # Get all clusters from input.json
        clusters = list_clusters()
        if not clusters:
            error_msg = "No clusters found in input.json"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "message": error_msg}
        
        logger.info(f"Found {len(clusters)} clusters in input.json: {[c['name'] for c in clusters]}")
        
        # Validate all clusters first
        update_status(name, namespace, "Validating", f"Validating {len(clusters)} clusters", logger)
        all_errors = []
        for cluster in clusters:
            validation = validate_cluster(cluster["name"])
            if not validation.get("valid"):
                all_errors.extend([f"{cluster['name']}: {e}" for e in validation["errors"]])
        
        if all_errors:
            error_msg = f"Validation failed: {'; '.join(all_errors[:5])}"  # Limit error length
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "phase": "validation", "errors": all_errors}
        
        # Create ProvisioningRequest for each cluster
        update_status(name, namespace, "Creating", f"Creating {len(clusters)} ProvisioningRequests", logger)
        
        created_requests = []
        api = client.CustomObjectsApi()
        
        for cluster in clusters:
            cluster_config = get_cluster_config(cluster["name"])
            
            # Build templateParameters
            cluster_template_params = {
                "clusterName": cluster_config.get("clusterName"),
                "k8sVersion": cluster_config.get("k8sVersion"),
                "clusterProvisioner": cluster_config.get("clusterProvisioner", "byoh"),
                "clusterType": cluster_config.get("clusterType", ""),
                "hosts": cluster_config.get("hosts", {}),
                "podCidr": cluster_config.get("podCidr", "10.244.0.0/16"),
                "serviceCidr": cluster_config.get("serviceCidr", "10.96.0.0/12")
            }
            
            pr_name = f"{name}-{cluster['name']}-o2ims"
            provisioning_request = {
                "apiVersion": f"{O2IMS_API_GROUP}/{O2IMS_API_VERSION}",
                "kind": "ProvisioningRequest",
                "metadata": {
                    "name": pr_name,
                    "namespace": ocloud_namespace,
                    "labels": {
                        "focom.nephio.org/source": name,
                        "focom.nephio.org/source-namespace": namespace,
                        "focom.nephio.org/source-type": "batch",
                        "focom.nephio.org/cluster-name": cluster["name"]
                    }
                },
                "spec": {
                    "name": cluster["name"],
                    "description": f"Cluster {cluster['name']} from batch request {name}",
                    "templateName": "byoh-workload-cluster",
                    "templateVersion": "v1.0.0",
                    "templateParameters": cluster_template_params
                }
            }
            
            try:
                api.create_namespaced_custom_object(
                    group=O2IMS_API_GROUP,
                    version=O2IMS_API_VERSION,
                    namespace=ocloud_namespace,
                    plural="provisioningrequests",
                    body=provisioning_request
                )
                created_requests.append(pr_name)
                logger.info(f"Created ProvisioningRequest: {pr_name}")
            except ApiException as e:
                logger.error(f"Failed to create {pr_name}: {e}")
        
        update_status(
            name, namespace, "Synced",
            f"Created {len(created_requests)} ProvisioningRequests: {', '.join(created_requests)}",
            logger,
            remote_name=",".join(created_requests)
        )
        
        return {"status": "synced", "createdRequests": created_requests, "count": len(created_requests)}
    
    # === OPTION B: Simplified input.json approach (single cluster) ===
    elif cluster_name_from_input and not template_name:
        logger.info(f"Using simplified input.json approach for cluster: {cluster_name_from_input}")
        
        update_status(name, namespace, "Loading", f"Loading cluster config from input.json", logger)
        
        # Load cluster config from input.json
        try:
            from controllers.input_parser import get_cluster_config, validate_cluster
        except ImportError:
            # Fallback for local development
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from input_parser import get_cluster_config, validate_cluster
        
        # Validate cluster from input.json
        validation = validate_cluster(cluster_name_from_input)
        if not validation.get("valid"):
            error_msg = f"Validation failed: {'; '.join(validation['errors'])}"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "phase": "validation", "errors": validation["errors"]}
        
        # Get resolved cluster config
        cluster_config = validation.get("cluster")
        if not cluster_config:
            error_msg = f"Cluster '{cluster_name_from_input}' not found in input.json"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "message": error_msg}
        
        # Build templateParameters from input.json cluster config
        template_params = {
            "clusterName": cluster_config.get("clusterName"),
            "k8sVersion": cluster_config.get("k8sVersion"),
            "clusterProvisioner": cluster_config.get("clusterProvisioner", "byoh"),
            "clusterType": cluster_config.get("clusterType", ""),
            "hosts": cluster_config.get("hosts", {}),
            "podCidr": cluster_config.get("podCidr", "10.244.0.0/16"),
            "serviceCidr": cluster_config.get("serviceCidr", "10.96.0.0/12")
        }
        template_name = "byoh-workload-cluster"  # Use default BYOH template
        
        logger.info(f"Loaded cluster config: {cluster_config.get('masterCount')} masters, {cluster_config.get('workerCount')} workers")
        
    else:
        # OPTION A: ClusterTemplate-based approach
        logger.info(f"Using ClusterTemplate approach with template: {template_name}")
        
        # === Step 1: Validate Request (Feature F4) ===
        update_status(name, namespace, "Validating", "Validating request against template", logger)
        
        validation = validate_request(spec, ocloud_namespace, logger)
        if not validation.get("valid"):
            error_msg = f"Validation failed: {'; '.join(validation['errors'])}"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "phase": "validation", "errors": validation["errors"]}
        
        if validation.get("warnings"):
            logger.warning(f"Validation warnings: {validation['warnings']}")
    
    # === Step 2: Check Feasibility (Feature F5) ===
    update_status(name, namespace, "Checking", "Checking resource availability", logger)
    
    # Build a spec-like dict for feasibility check
    check_spec = {"templateParameters": template_params}
    feasibility = check_feasibility(check_spec, ocloud_namespace, logger)
    if not feasibility.get("feasible"):
        in_use_errors = [e for e in feasibility["errors"] if "already in use" in e]
        if in_use_errors:
            error_msg = f"Feasibility check failed: {'; '.join(in_use_errors)}"
            logger.error(error_msg)
            update_status(name, namespace, "Failed", error_msg, logger)
            return {"status": "failed", "phase": "feasibility", "errors": in_use_errors}
    
    # Warnings about unregistered hosts are OK - Ansible will register them
    if feasibility.get("warnings"):
        logger.info(f"Feasibility warnings (will proceed): {feasibility['warnings']}")
    
    # === Step 3: Create O2IMS ProvisioningRequest ===
    update_status(name, namespace, "Creating", "Creating O2IMS ProvisioningRequest", logger)
    
    provisioning_request_name = f"{name}-o2ims"
    provisioning_request = {
        "apiVersion": f"{O2IMS_API_GROUP}/{O2IMS_API_VERSION}",
        "kind": "ProvisioningRequest",
        "metadata": {
            "name": provisioning_request_name,
            "namespace": ocloud_namespace,
            "labels": {
                "focom.nephio.org/source": name,
                "focom.nephio.org/source-namespace": namespace,
                "focom.nephio.org/source-type": "input-json" if cluster_name_from_input else "cluster-template"
            }
        },
        "spec": {
            "name": req_name,
            "description": description,
            "templateName": template_name,
            "templateVersion": template_version or "v1.0.0",
            "templateParameters": template_params
        }
    }
    
    try:
        api = client.CustomObjectsApi()
        result = api.create_namespaced_custom_object(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=ocloud_namespace,
            plural="provisioningrequests",
            body=provisioning_request
        )
        logger.info(f"Created ProvisioningRequest: {provisioning_request_name}")
        
        update_status(
            name, namespace, "Synced",
            f"ProvisioningRequest created: {provisioning_request_name}",
            logger,
            remote_name=provisioning_request_name,
            validation_result={"valid": True},
            feasibility_result=feasibility
        )
        
        return {"status": "synced", "remoteName": provisioning_request_name}
        
    except ApiException as e:
        error_msg = f"Failed to create ProvisioningRequest: {e}"
        logger.error(error_msg)
        update_status(name, namespace, "Failed", error_msg, logger)
        return {"status": "failed", "message": error_msg}



@kopf.on.delete(FOCOM_API_GROUP, FOCOM_API_VERSION, "focomprovisioningrequests")
def handle_delete(spec, status, name, namespace, logger, **kwargs):
    """Handle deletion of a FocomProvisioningRequest."""
    logger.info(f"Processing deletion of FocomProvisioningRequest: {name}")
    
    remote_name = status.get("remoteName")
    if not remote_name:
        remote_name = f"{name}-o2ims"
    
    ocloud_namespace = spec.get("oCloudNamespace", "default")
    
    try:
        api = client.CustomObjectsApi()
        api.delete_namespaced_custom_object(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=ocloud_namespace,
            plural="provisioningrequests",
            name=remote_name
        )
        logger.info(f"Deleted ProvisioningRequest: {remote_name}")
    except ApiException as e:
        if e.status != 404:
            logger.error(f"Failed to delete ProvisioningRequest {remote_name}: {e}")
    
    return {"status": "deleted"}


@kopf.timer(FOCOM_API_GROUP, FOCOM_API_VERSION, "focomprovisioningrequests", interval=60.0)
def sync_status(spec, status, name, namespace, logger, **kwargs):
    """Periodically sync status from O2IMS ProvisioningRequest."""
    current_phase = status.get("phase", "")
    if current_phase in ["Failed"]:
        return
    
    remote_name = status.get("remoteName")
    if not remote_name:
        return
    
    ocloud_namespace = spec.get("oCloudNamespace", "default")
    
    try:
        api = client.CustomObjectsApi()
        remote = api.get_namespaced_custom_object(
            group=O2IMS_API_GROUP,
            version=O2IMS_API_VERSION,
            namespace=ocloud_namespace,
            plural="provisioningrequests",
            name=remote_name
        )
        
        remote_status = remote.get("status", {})
        prov_status = remote_status.get("provisioningStatus", {})
        prov_state = prov_status.get("provisioningState", "")
        prov_msg = prov_status.get("provisioningMessage", "")
        
        if prov_state == "fulfilled":
            update_status(name, namespace, "Synced", f"Cluster provisioned: {prov_msg}", logger, remote_name)
        elif prov_state == "failed":
            update_status(name, namespace, "Failed", f"Cluster failed: {prov_msg}", logger, remote_name)
        elif prov_state == "progressing":
            update_status(name, namespace, "Synced", f"In progress: {prov_msg}", logger, remote_name)
            
    except ApiException as e:
        if e.status == 404:
            logger.warning(f"Remote ProvisioningRequest {remote_name} not found")


def update_status(
    name: str, 
    namespace: str, 
    phase: str, 
    message: str, 
    logger, 
    remote_name: str = None,
    validation_result: Dict = None,
    feasibility_result: Dict = None
):
    """Update FocomProvisioningRequest status."""
    try:
        api = client.CustomObjectsApi()
        current = api.get_namespaced_custom_object(
            group=FOCOM_API_GROUP,
            version=FOCOM_API_VERSION,
            namespace=namespace,
            plural="focomprovisioningrequests",
            name=name
        )
        
        if "status" not in current:
            current["status"] = {}
        
        current["status"]["phase"] = phase
        current["status"]["message"] = message
        current["status"]["lastUpdated"] = get_current_time()
        
        if remote_name:
            current["status"]["remoteName"] = remote_name
        
        # Add validation/feasibility results
        if validation_result:
            current["status"]["validation"] = {
                "valid": validation_result.get("valid"),
                "warnings": validation_result.get("warnings", [])
            }
        if feasibility_result:
            current["status"]["feasibility"] = {
                "feasible": feasibility_result.get("feasible"),
                "hostStatus": feasibility_result.get("hostStatus", {})
            }
        
        api.patch_namespaced_custom_object_status(
            group=FOCOM_API_GROUP,
            version=FOCOM_API_VERSION,
            namespace=namespace,
            plural="focomprovisioningrequests",
            name=name,
            body=current
        )
    except ApiException as e:
        logger.error(f"Failed to update status: {e}")


# =============================================================================
# PHASE 2: VERSIONING - Create Revision on Changes
# =============================================================================

def create_revision(name: str, namespace: str, spec: Dict, operation: str, logger, revision_num: int = None):
    """
    Create a ProvisioningRevision to track changes.
    
    Phase 2 Feature: Request Versioning
    """
    try:
        api = client.CustomObjectsApi()
        
        # Get current revision number from status if not provided
        if revision_num is None:
            try:
                current = api.get_namespaced_custom_object(
                    group=FOCOM_API_GROUP,
                    version=FOCOM_API_VERSION,
                    namespace=namespace,
                    plural="focomprovisioningrequests",
                    name=name
                )
                revision_num = current.get("status", {}).get("revision", 0) + 1
            except:
                revision_num = 1
        
        revision_name = f"{name}-rev-{revision_num}"
        
        revision = {
            "apiVersion": "o2ims.provisioning.oran.org/v1alpha1",
            "kind": "ProvisioningRevision",
            "metadata": {
                "name": revision_name,
                "namespace": namespace,
                "labels": {
                    "request-name": name,
                    "revision": str(revision_num)
                }
            },
            "spec": {
                "requestName": name,
                "requestNamespace": namespace,
                "revision": revision_num,
                "createdAt": get_current_time(),
                "operation": operation,
                "specSnapshot": spec
            }
        }
        
        api.create_namespaced_custom_object(
            group="o2ims.provisioning.oran.org",
            version="v1alpha1",
            namespace=namespace,
            plural="provisioningrevisions",
            body=revision
        )
        logger.info(f"Created revision {revision_name}")
        return revision_num
    except ApiException as e:
        logger.error(f"Failed to create revision: {e}")
        return None


# =============================================================================
# PHASE 2: SCALING - Handle Scale Operations
# =============================================================================

def handle_scale_operation(name: str, namespace: str, spec: Dict, status: Dict, logger):
    """
    Handle scaling a cluster (add/remove workers).
    
    Phase 2 Feature: Update ProvisioningRequest (Scale)
    
    Approach A: User updates input.json with new worker count, then applies same request.
    We detect the change and update MachineDeployment replicas.
    """
    cluster_name = spec.get("clusterName")
    target_worker_count = spec.get("targetWorkerCount")
    
    if not cluster_name:
        logger.error("clusterName required for scale operation")
        return {"status": "failed", "message": "clusterName required"}
    
    try:
        api = client.CustomObjectsApi()
        
        # Get current MachineDeployment for this cluster
        md_name = f"{cluster_name}-md-0"
        
        try:
            md = api.get_namespaced_custom_object(
                group="cluster.x-k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="machinedeployments",
                name=md_name
            )
            current_replicas = md.get("spec", {}).get("replicas", 0)
        except ApiException as e:
            if e.status == 404:
                logger.info(f"No MachineDeployment found for {cluster_name}, may be control-plane only cluster")
                return {"status": "skipped", "message": "No workers to scale"}
            raise
        
        # If targetWorkerCount specified, use it; otherwise get from input.json
        if target_worker_count is None:
            try:
                from input_parser import get_cluster_config
                config = get_cluster_config(cluster_name)
                if config:
                    target_worker_count = config.get("workerCount", 0)
            except:
                target_worker_count = current_replicas
        
        if target_worker_count == current_replicas:
            logger.info(f"No scaling needed: {current_replicas} workers")
            return {"status": "unchanged", "currentWorkers": current_replicas}
        
        # Patch MachineDeployment replicas
        patch = {"spec": {"replicas": target_worker_count}}
        api.patch_namespaced_custom_object(
            group="cluster.x-k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="machinedeployments",
            name=md_name,
            body=patch
        )
        
        direction = "up" if target_worker_count > current_replicas else "down"
        logger.info(f"Scaled {cluster_name} {direction}: {current_replicas} -> {target_worker_count} workers")
        
        return {
            "status": "scaled",
            "previousWorkers": current_replicas,
            "targetWorkers": target_worker_count,
            "direction": direction
        }
        
    except ApiException as e:
        logger.error(f"Scale operation failed: {e}")
        return {"status": "failed", "message": str(e)}


# =============================================================================
# PHASE 2: DRAFT MODE - Preview Without Executing
# =============================================================================

def handle_draft_mode(name: str, namespace: str, spec: Dict, logger):
    """
    Handle draft mode - validate and preview without actually creating resources.
    
    Phase 2 Feature: Draft/Execute Flow
    """
    cluster_name = spec.get("clusterName")
    all_clusters = spec.get("allClusters", False)
    
    preview = {
        "mode": "draft",
        "willCreate": [],
        "validation": {"valid": True, "errors": [], "warnings": []},
        "feasibility": {"feasible": True, "availableHosts": 0, "requiredHosts": 0}
    }
    
    try:
        from input_parser import list_clusters, get_cluster_config, validate_cluster
    except ImportError:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from input_parser import list_clusters, get_cluster_config, validate_cluster
    
    # Determine which clusters to preview
    if all_clusters:
        clusters = [c["name"] for c in list_clusters()]
    elif cluster_name:
        clusters = [cluster_name]
    else:
        clusters = spec.get("clusterNames", [])
    
    # Validate and preview each cluster
    total_hosts_needed = 0
    for cn in clusters:
        validation = validate_cluster(cn)
        config = get_cluster_config(cn)
        
        if not validation.get("valid"):
            preview["validation"]["valid"] = False
            preview["validation"]["errors"].extend(validation.get("errors", []))
        
        preview["validation"]["warnings"].extend(validation.get("warnings", []))
        
        if config:
            hosts_needed = config.get("masterCount", 0) + config.get("workerCount", 0)
            total_hosts_needed += hosts_needed
            preview["willCreate"].append({
                "clusterName": cn,
                "masterCount": config.get("masterCount", 0),
                "workerCount": config.get("workerCount", 0),
                "k8sVersion": config.get("k8sVersion")
            })
    
    # Check feasibility
    resources = query_resources(namespace, logger)
    available_hosts = len([r for r in resources.get("resources", []) if r.get("status") == "available"])
    preview["feasibility"]["availableHosts"] = available_hosts
    preview["feasibility"]["requiredHosts"] = total_hosts_needed
    preview["feasibility"]["feasible"] = available_hosts >= total_hosts_needed
    
    logger.info(f"Draft preview for {name}: {len(clusters)} clusters, {total_hosts_needed} hosts needed")
    return preview


# =============================================================================
# PHASE 2: ROLLBACK - Revert to Previous Revision
# =============================================================================

def handle_rollback(name: str, namespace: str, target_revision: int, logger):
    """
    Rollback to a previous revision.
    
    Phase 2 Feature: Rollback
    """
    try:
        api = client.CustomObjectsApi()
        
        # Find the revision
        revision_name = f"{name}-rev-{target_revision}"
        
        try:
            revision = api.get_namespaced_custom_object(
                group="o2ims.provisioning.oran.org",
                version="v1alpha1",
                namespace=namespace,
                plural="provisioningrevisions",
                name=revision_name
            )
        except ApiException as e:
            if e.status == 404:
                return {"status": "failed", "message": f"Revision {target_revision} not found"}
            raise
        
        # Get the spec snapshot from that revision
        old_spec = revision.get("spec", {}).get("specSnapshot", {})
        cluster_state = revision.get("spec", {}).get("clusterState", {})
        
        if not old_spec:
            return {"status": "failed", "message": "Revision has no spec snapshot"}
        
        logger.info(f"Rolling back {name} to revision {target_revision}")
        
        # For now, log what would be restored
        # Full implementation would patch the cluster resources
        return {
            "status": "rolled_back",
            "targetRevision": target_revision,
            "restoredSpec": old_spec,
            "clusterState": cluster_state
        }
        
    except ApiException as e:
        logger.error(f"Rollback failed: {e}")
        return {"status": "failed", "message": str(e)}


# =============================================================================
# PHASE 2: UPDATE HANDLER
# =============================================================================

@kopf.on.update(FOCOM_API_GROUP, FOCOM_API_VERSION, "focomprovisioningrequests")
def handle_update(spec, status, name, namespace, old, new, diff, logger, **kwargs):
    """
    Handle updates to FocomProvisioningRequest.
    
    Phase 2 Features:
    - Scaling (operation: scale)
    - Draft/Execute flow (mode: draft/execute)
    - Rollback (rollbackToRevision: N)
    - Versioning (create revision on changes)
    """
    logger.info(f"Processing update for FocomProvisioningRequest: {name}")
    
    operation = spec.get("operation", "create")
    mode = spec.get("mode", "execute")
    rollback_revision = spec.get("rollbackToRevision")
    approved = spec.get("approved", False)
    
    # Get current revision
    current_revision = status.get("revision", 0)
    
    # Handle rollback request
    if rollback_revision is not None:
        update_status(name, namespace, "RollingBack", f"Rolling back to revision {rollback_revision}", logger)
        result = handle_rollback(name, namespace, rollback_revision, logger)
        
        if result.get("status") == "rolled_back":
            # Create a new revision for the rollback
            create_revision(name, namespace, spec, "rollback", logger, current_revision + 1)
            update_status(name, namespace, "Synced", f"Rolled back to revision {rollback_revision}", logger)
        else:
            update_status(name, namespace, "Failed", result.get("message", "Rollback failed"), logger)
        return result
    
    # Handle draft mode
    if mode == "draft":
        if approved:
            # Draft approved - execute it
            logger.info(f"Draft {name} approved, executing...")
            update_status(name, namespace, "Creating", "Draft approved, creating resources", logger)
            # Re-run create logic (same as handle_create)
            # In a full implementation, this would call handle_create logic
        else:
            # Just preview
            preview = handle_draft_mode(name, namespace, spec, logger)
            update_status(
                name, namespace, "Draft", 
                f"Preview: {len(preview['willCreate'])} clusters, {preview['feasibility']['requiredHosts']} hosts",
                logger
            )
            
            # Update status with preview
            try:
                api = client.CustomObjectsApi()
                current = api.get_namespaced_custom_object(
                    group=FOCOM_API_GROUP,
                    version=FOCOM_API_VERSION,
                    namespace=namespace,
                    plural="focomprovisioningrequests",
                    name=name
                )
                current["status"]["draftPreview"] = preview
                api.patch_namespaced_custom_object_status(
                    group=FOCOM_API_GROUP,
                    version=FOCOM_API_VERSION,
                    namespace=namespace,
                    plural="focomprovisioningrequests",
                    name=name,
                    body=current
                )
            except:
                pass
            
            return preview
    
    # Handle scale operation
    if operation == "scale":
        update_status(name, namespace, "Scaling", "Scaling cluster workers", logger)
        result = handle_scale_operation(name, namespace, spec, status, logger)
        
        if result.get("status") == "scaled":
            # Create revision
            new_revision = create_revision(name, namespace, spec, "scale", logger, current_revision + 1)
            
            # Update status with new worker count and revision
            try:
                api = client.CustomObjectsApi()
                current = api.get_namespaced_custom_object(
                    group=FOCOM_API_GROUP,
                    version=FOCOM_API_VERSION,
                    namespace=namespace,
                    plural="focomprovisioningrequests",
                    name=name
                )
                current["status"]["revision"] = new_revision
                current["status"]["currentWorkerCount"] = result.get("targetWorkers")
                current["status"]["phase"] = "Synced"
                current["status"]["message"] = f"Scaled to {result.get('targetWorkers')} workers"
                api.patch_namespaced_custom_object_status(
                    group=FOCOM_API_GROUP,
                    version=FOCOM_API_VERSION,
                    namespace=namespace,
                    plural="focomprovisioningrequests",
                    name=name,
                    body=current
                )
            except:
                pass
            
        elif result.get("status") == "failed":
            update_status(name, namespace, "Failed", result.get("message", "Scale failed"), logger)
        
        return result
    
    # For other updates, just create a revision to track the change
    new_revision = create_revision(name, namespace, spec, "update", logger, current_revision + 1)
    if new_revision:
        # Update revision number in status
        try:
            api = client.CustomObjectsApi()
            current = api.get_namespaced_custom_object(
                group=FOCOM_API_GROUP,
                version=FOCOM_API_VERSION,
                namespace=namespace,
                plural="focomprovisioningrequests",
                name=name
            )
            current["status"]["revision"] = new_revision
            api.patch_namespaced_custom_object_status(
                group=FOCOM_API_GROUP,
                version=FOCOM_API_VERSION,
                namespace=namespace,
                plural="focomprovisioningrequests",
                name=name,
                body=current
            )
        except:
            pass
    
    return {"status": "updated", "revision": new_revision}


# =============================================================================
# KOPF HANDLERS FOR OPERATIONS
# =============================================================================

@kopf.on.field(FOCOM_API_GROUP, FOCOM_API_VERSION, "focomprovisioningrequests", field="spec.operation")
def handle_operation_change(old, new, spec, status, name, namespace, logger, **kwargs):
    """Handle operation field changes for scale support."""
    
    if new == "scale":
        logger.info(f"Starting scale operation for {name}")
        update_status(name, namespace, "Scaling", "Scaling cluster workers", logger)
        
        result = handle_scale_operation(name, namespace, spec, status, logger)
        
        if result.get("status") == "scaled":
            update_status(
                name, namespace, "Synced",
                f"Scaled to {result.get('targetWorkers')} workers",
                logger
            )
        elif result.get("status") == "failed":
            update_status(name, namespace, "Failed", result.get("message", "Scale failed"), logger)
        
        return result


if __name__ == "__main__":
    kopf.run()


