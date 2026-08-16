"""
O2IMS ProvisioningRequest Controller for BYOH Cluster Provisioning

This controller watches for ProvisioningRequest CRs and creates BYOH CAPI
cluster resources directly, replacing the Porch/PackageVariant approach
from the original Nephio implementation.

Uses the kopf framework for Kubernetes operator development.
"""

import kopf
import logging
import uuid
import time
import os
from datetime import datetime

from utils import ProvisioningState, TIME_FORMAT, get_current_time
from utils.k8s_utils import (
    init_k8s_client,
    get_capi_cluster,
    apply_k8s_resource,
    update_provisioning_request_status,
    delete_cluster_resources,
    label_byohost,
    get_byohost,
)
from byoh_cluster_generator import generate_byoh_cluster_resources
from ansible_job_manager import run_host_registration

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API constants
O2IMS_API_GROUP = "o2ims.provisioning.oran.org"
O2IMS_API_VERSION = "v1alpha1"

# Timeouts
CLUSTER_CREATION_TIMEOUT = 1800  # 30 minutes


@kopf.on.startup()
def startup_handler(settings: kopf.OperatorSettings, **kwargs):
    """Initialize the operator on startup."""
    logger.info("O2IMS Operator for BYOH starting up...")
    init_k8s_client()
    
    # Configure kopf settings
    settings.persistence.finalizer = f"{O2IMS_API_GROUP}/kopf-finalizer"
    settings.posting.level = logging.WARNING


# Configuration for Ansible job - uses environment variable for portability
# BYOH_PROJECT_DIR should be set to the absolute path where the repo is cloned
PROJECT_DIR = os.environ.get("BYOH_PROJECT_DIR", "/opt/byoh-o2ims-focom")


@kopf.on.create(O2IMS_API_GROUP, O2IMS_API_VERSION, "provisioningrequests")
def handle_create(spec, name, namespace, logger, **kwargs):
    """
    Handle creation of a new ProvisioningRequest.
    
    This triggers the BYOH cluster provisioning workflow:
    1. Validate the request
    2. Check if hosts are registered (run Ansible if not)
    3. Generate BYOH CAPI resources
    4. Apply resources to the cluster
    5. Monitor cluster status until provisioned
    """
    logger.info(f"Processing new ProvisioningRequest: {name}")
    
    # Extract parameters from spec
    template_params = spec.get("templateParameters", {})
    cluster_name = template_params.get("clusterName")
    cluster_provisioner = template_params.get("clusterProvisioner", "byoh")
    k8s_version = template_params.get("k8sVersion", "v1.32.0")
    hosts = template_params.get("hosts", {})
    
    # Validate required fields
    if not cluster_name:
        error_msg = "templateParameters.clusterName is required"
        logger.error(error_msg)
        update_status(name, namespace, ProvisioningState.FAILED, error_msg, logger)
        return {"status": "failed", "message": error_msg}
    
    if cluster_provisioner != "byoh":
        error_msg = f"Unsupported clusterProvisioner: {cluster_provisioner}. Only 'byoh' is supported."
        logger.error(error_msg)
        update_status(name, namespace, ProvisioningState.FAILED, error_msg, logger)
        return {"status": "failed", "message": error_msg}
    
    masters = hosts.get("masters", [])
    workers = hosts.get("workers", [])
    
    if not masters:
        error_msg = "At least one master node is required in templateParameters.hosts.masters"
        logger.error(error_msg)
        update_status(name, namespace, ProvisioningState.FAILED, error_msg, logger)
        return {"status": "failed", "message": error_msg}
    
    # Check if hosts are registered as ByoHosts
    all_hosts = masters + workers
    unregistered_hosts = []
    
    for host in all_hosts:
        host_name = host.get("hostName", host.get("host_name"))
        if host_name:
            result = get_byohost(host_name, namespace, logger)
            if not result.get("status"):
                unregistered_hosts.append(host_name)
    
    # If any hosts are not registered, run Ansible playbook to register them
    if unregistered_hosts:
        logger.info(f"Hosts not registered: {unregistered_hosts}. Running Ansible to register...")
        update_status(
            name, namespace,
            ProvisioningState.PROGRESSING,
            f"Registering hosts: {', '.join(unregistered_hosts)}",
            logger
        )
        
        # Run Ansible job to register hosts
        ansible_result = run_host_registration(
            request_name=name,
            cluster_name=cluster_name,
            project_dir=PROJECT_DIR,
            namespace="o2ims-system",
            logger=logger
        )
        
        if not ansible_result.get("status"):
            error_msg = f"Failed to register hosts: {ansible_result.get('error', 'Ansible job failed')}"
            logger.error(error_msg)
            update_status(name, namespace, ProvisioningState.FAILED, error_msg, logger)
            return {"status": "failed", "message": error_msg}
        
        logger.info("Hosts registered successfully via Ansible")
        # Wait for ByoHosts to appear in cluster
        time.sleep(15)
    else:
        logger.info("All hosts are registered as ByoHosts, proceeding with cluster creation")
    
    # Update status to progressing
    update_status(
        name, namespace, 
        ProvisioningState.PROGRESSING, 
        "Generating BYOH cluster resources",
        logger
    )
    
    try:
        # Label ByoHosts with host-id for selector matching
        logger.info("Labeling ByoHosts for cluster pinning...")
        all_hosts = masters + workers
        for host in all_hosts:
            host_id = host.get("hostId", host.get("host_id"))
            host_name = host.get("hostName", host.get("host_name"))
            if host_name and host_id:
                label_byohost(
                    name=host_name,
                    labels={"host-id": str(host_id)},
                    namespace=namespace,
                    logger=logger
                )
        
        # Generate BYOH CAPI resources
        logger.info(f"Generating BYOH resources for cluster: {cluster_name}")
        resources = generate_byoh_cluster_resources(
            cluster_name=cluster_name,
            masters=masters,
            workers=workers,
            k8s_version=k8s_version,
            namespace=namespace,
            pod_cidr=template_params.get("podCidr", "10.244.0.0/16"),
            service_cidr=template_params.get("serviceCidr", "10.96.0.0/12"),
        )
        
        # Apply resources
        update_status(
            name, namespace,
            ProvisioningState.PROGRESSING,
            "Applying cluster resources",
            logger
        )
        
        for resource in resources:
            kind = resource.get("kind")
            res_name = resource.get("metadata", {}).get("name")
            logger.info(f"Applying {kind}/{res_name}")
            result = apply_k8s_resource(resource, namespace, logger)
            if not result.get("status"):
                raise Exception(f"Failed to apply {kind}/{res_name}: {result.get('error')}")
        
        # Update status - now monitoring
        update_status(
            name, namespace,
            ProvisioningState.PROGRESSING,
            "Cluster resources applied, waiting for provisioning",
            logger
        )
        
        logger.info(f"Cluster resources applied. Monitoring cluster: {cluster_name}")
        return {
            "status": "progressing",
            "clusterName": cluster_name,
            "message": "Cluster resources applied, monitoring provisioning"
        }
        
    except Exception as e:
        error_msg = f"Failed to create cluster: {str(e)}"
        logger.error(error_msg)
        update_status(name, namespace, ProvisioningState.FAILED, error_msg, logger)
        return {"status": "failed", "message": error_msg}


@kopf.timer(O2IMS_API_GROUP, O2IMS_API_VERSION, "provisioningrequests", interval=30.0)
def monitor_cluster_status(spec, status, name, namespace, logger, **kwargs):
    """
    Periodically check cluster provisioning status.
    
    This timer runs every 30 seconds to check if the CAPI cluster
    has reached 'Provisioned' state.
    """
    # Get current provisioning state
    current_status = status.get("provisioningStatus", {})
    current_state = current_status.get("provisioningState", "")
    
    # Skip if already fulfilled, failed, or deleting
    if current_state in [ProvisioningState.FULFILLED, ProvisioningState.FAILED, ProvisioningState.DELETING]:
        return
    
    # Get cluster name from spec
    template_params = spec.get("templateParameters", {})
    cluster_name = template_params.get("clusterName")
    
    if not cluster_name:
        return
    
    # Check CAPI cluster status
    cluster_result = get_capi_cluster(cluster_name, namespace, logger)
    
    if cluster_result.get("status"):
        cluster = cluster_result.get("body", {})
        cluster_status = cluster.get("status", {})
        phase = cluster_status.get("phase", "")
        
        logger.debug(f"Cluster {cluster_name} phase: {phase}")
        
        if phase == "Provisioned":
            # Cluster is ready!
            logger.info(f"Cluster {cluster_name} is now Provisioned!")
            
            # Generate resource IDs
            cluster_id = str(uuid.uuid4())
            infra_ids = [str(uuid.uuid4())]
            
            update_provisioning_request_status(
                name=name,
                namespace=namespace,
                status_update={
                    "provisioningStatus": {
                        "provisioningState": ProvisioningState.FULFILLED,
                        "provisioningMessage": "Cluster successfully provisioned",
                        "provisioningUpdateTime": get_current_time()
                    },
                    "provisionedResourceSet": {
                        "oCloudNodeClusterId": cluster_id,
                        "oCloudInfrastructureResourceIds": infra_ids
                    }
                },
                logger=logger
            )
            
        elif phase == "Failed":
            # Cluster provisioning failed
            failure_msg = cluster_status.get("failureMessage", "Unknown failure")
            logger.error(f"Cluster {cluster_name} failed: {failure_msg}")
            update_status(name, namespace, ProvisioningState.FAILED, failure_msg, logger)
    else:
        # Cluster not found yet, still pending
        logger.debug(f"Cluster {cluster_name} not found yet, waiting...")


@kopf.on.delete(O2IMS_API_GROUP, O2IMS_API_VERSION, "provisioningrequests")
def handle_delete(spec, name, namespace, logger, **kwargs):
    """
    Handle deletion of a ProvisioningRequest.
    
    This cleans up the associated CAPI cluster resources.
    """
    logger.info(f"Processing deletion of ProvisioningRequest: {name}")
    
    # Get cluster name
    template_params = spec.get("templateParameters", {})
    cluster_name = template_params.get("clusterName")
    
    if cluster_name:
        logger.info(f"Deleting cluster: {cluster_name}")
        result = delete_cluster_resources(cluster_name, namespace, logger)
        
        if result.get("status"):
            logger.info(f"Cluster {cluster_name} deletion initiated")
        else:
            logger.warning(f"Could not delete cluster {cluster_name}: {result.get('error')}")
    
    return {"status": "deleted"}


@kopf.on.update(O2IMS_API_GROUP, O2IMS_API_VERSION, "provisioningrequests")
def handle_update(spec, old, new, name, namespace, logger, **kwargs):
    """
    Handle updates to a ProvisioningRequest.
    
    Note: Currently, updates to templateParameters are not supported
    after initial creation. The cluster must be deleted and recreated.
    """
    old_params = old.get("spec", {}).get("templateParameters", {})
    new_params = new.get("spec", {}).get("templateParameters", {})
    
    if old_params != new_params:
        logger.warning(
            f"ProvisioningRequest {name}: templateParameters changes are not supported. "
            "Delete and recreate the ProvisioningRequest to apply changes."
        )
    
    return {"status": "no-op"}


def update_status(name: str, namespace: str, state: str, message: str, logger):
    """Helper to update ProvisioningRequest status."""
    update_provisioning_request_status(
        name=name,
        namespace=namespace,
        status_update={
            "provisioningStatus": {
                "provisioningState": state,
                "provisioningMessage": message,
                "provisioningUpdateTime": get_current_time()
            }
        },
        logger=logger
    )


if __name__ == "__main__":
    # Run the operator
    kopf.run()
