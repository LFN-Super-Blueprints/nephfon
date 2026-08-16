"""
Ansible Job Manager for O2IMS Operator

Creates and monitors Kubernetes Jobs to run ansible-playbook
for host registration on the management node.
"""

import os
import time
import logging
import uuid
from typing import Dict, Any, Optional
from kubernetes import client
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Job configuration
# Use custom image with Ansible + kubectl, or a public image that has both
ANSIBLE_IMAGE = "ansible-runner:local"  # Custom image built from ansible-runner/Dockerfile
DEFAULT_TIMEOUT = 900  # 15 minutes for full playbook
JOB_NAMESPACE = "o2ims-system"

# Path configuration - use environment variables for portability
# These should be set based on the user's environment
DEFAULT_PROJECT_DIR = os.environ.get("BYOH_PROJECT_DIR", "/opt/byoh-o2ims-focom")
DEFAULT_SSH_DIR = os.environ.get("BYOH_SSH_DIR", os.path.expanduser("~/.ssh"))
DEFAULT_KUBE_DIR = os.environ.get("BYOH_KUBE_DIR", os.path.expanduser("~/.kube"))


def create_ansible_job(
    job_name: str,
    playbook_path: str,
    project_dir: str = None,
    ssh_dir: str = None,
    kube_dir: str = None,
    kubeconfig_path: str = "/etc/kubernetes/admin.conf",
    extra_vars: Optional[Dict[str, str]] = None,
    namespace: str = JOB_NAMESPACE,
    logger=None
) -> Dict[str, Any]:
    """
    Create a Kubernetes Job to run an Ansible playbook.
    
    Args:
        job_name: Name for the Job
        playbook_path: Path to playbook (relative to project_dir)
        project_dir: Path to project directory on host (default: BYOH_PROJECT_DIR env var)
        ssh_dir: Path to SSH keys on host (default: BYOH_SSH_DIR env var or ~/.ssh)
        kube_dir: Path to kube config dir on host (default: BYOH_KUBE_DIR env var or ~/.kube)
        kubeconfig_path: Path to kubeconfig on host
        extra_vars: Extra variables to pass to ansible-playbook
        namespace: Namespace to create Job in
        logger: Logger instance
    
    Returns:
        dict with 'status' (bool) and 'job_name'
    """
    # Apply defaults from environment variables
    project_dir = project_dir or DEFAULT_PROJECT_DIR
    ssh_dir = ssh_dir or DEFAULT_SSH_DIR
    kube_dir = kube_dir or DEFAULT_KUBE_DIR
    
    batch_api = client.BatchV1Api()
    
    # Build ansible-playbook command
    # NOTE: No inventory flag - site.yaml uses dynamic inventory via add_host in Play 1
    command = [
        "ansible-playbook",
        f"/workspace/{playbook_path}",
        "-v",  # Verbose output
    ]
    
    # Add extra variables if provided
    if extra_vars:
        for key, value in extra_vars.items():
            command.extend(["-e", f"{key}={value}"])
    
    # Job specification
    job_spec = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=namespace,
            labels={
                "app": "ansible-host-registration",
                "o2ims.oran.org/managed-by": "o2ims-operator"
            }
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=600,  # Clean up after 10 minutes
            backoff_limit=1,  # Only retry once
            active_deadline_seconds=DEFAULT_TIMEOUT,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"app": "ansible-host-registration"}
                ),
                spec=client.V1PodSpec(
                    # Run on management node where files exist
                    node_selector={
                        "node-role.kubernetes.io/control-plane": ""
                    },
                    tolerations=[
                        client.V1Toleration(
                            key="node-role.kubernetes.io/control-plane",
                            operator="Exists",
                            effect="NoSchedule"
                        ),
                        client.V1Toleration(
                            key="node-role.kubernetes.io/master",
                            operator="Exists",
                            effect="NoSchedule"
                        )
                    ],
                    containers=[
                        client.V1Container(
                            name="ansible",
                            image=ANSIBLE_IMAGE,
                            image_pull_policy="Never",  # Local image
                            command=command,
                            working_dir="/workspace",
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="project-dir",
                                    mount_path="/workspace"
                                ),
                                client.V1VolumeMount(
                                    name="ssh-keys",
                                    mount_path="/root/.ssh",
                                    read_only=True
                                ),
                                client.V1VolumeMount(
                                    name="kubeconfig",
                                    mount_path="/root/.kube",
                                    read_only=True
                                )
                            ],
                            env=[
                                client.V1EnvVar(
                                    name="ANSIBLE_HOST_KEY_CHECKING",
                                    value="False"
                                ),
                                client.V1EnvVar(
                                    name="KUBECONFIG",
                                    value="/root/.kube/config"
                                ),
                                client.V1EnvVar(
                                    name="ANSIBLE_FORCE_COLOR",
                                    value="true"
                                )
                            ]
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="project-dir",
                            host_path=client.V1HostPathVolumeSource(
                                path=project_dir,
                                type="Directory"
                            )
                        ),
                        client.V1Volume(
                            name="ssh-keys",
                            host_path=client.V1HostPathVolumeSource(
                                path=ssh_dir,
                                type="Directory"
                            )
                        ),
                        client.V1Volume(
                            name="kubeconfig",
                            host_path=client.V1HostPathVolumeSource(
                                path=kube_dir,
                                type="Directory"
                            )
                        )
                    ],
                    restart_policy="Never"
                )
            )
        )
    )
    
    
    try:
        # Delete existing job if any
        try:
            batch_api.delete_namespaced_job(
                name=job_name,
                namespace=namespace,
                propagation_policy="Background"
            )
            time.sleep(2)  # Wait for deletion
        except ApiException as e:
            if e.status != 404:
                raise
        
        # Create the job
        result = batch_api.create_namespaced_job(
            namespace=namespace,
            body=job_spec
        )
        
        if logger:
            logger.info(f"Created Ansible Job: {job_name}")
        
        return {"status": True, "job_name": job_name}
        
    except ApiException as e:
        if logger:
            logger.error(f"Failed to create Ansible Job: {e}")
        return {"status": False, "error": str(e)}


def wait_for_ansible_job(
    job_name: str,
    namespace: str = JOB_NAMESPACE,
    timeout: int = DEFAULT_TIMEOUT,
    logger=None
) -> Dict[str, Any]:
    """
    Wait for an Ansible Job to complete.
    
    Args:
        job_name: Name of the Job
        namespace: Namespace of the Job
        timeout: Maximum seconds to wait
        logger: Logger instance
    
    Returns:
        dict with 'status' (bool), 'succeeded', and optional 'logs'
    """
    batch_api = client.BatchV1Api()
    core_api = client.CoreV1Api()
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            job = batch_api.read_namespaced_job_status(
                name=job_name,
                namespace=namespace
            )
            
            status = job.status
            
            # Check if completed
            if status.succeeded and status.succeeded > 0:
                if logger:
                    logger.info(f"Ansible Job {job_name} completed successfully")
                return {"status": True, "succeeded": True}
            
            # Check if failed
            if status.failed and status.failed > 0:
                # Get logs for debugging
                logs = get_job_logs(job_name, namespace, core_api)
                if logger:
                    logger.error(f"Ansible Job {job_name} failed. Logs: {logs}")
                return {"status": False, "succeeded": False, "logs": logs}
            
            # Still running
            if logger:
                logger.debug(f"Ansible Job {job_name} still running...")
            time.sleep(10)
            
        except ApiException as e:
            if logger:
                logger.error(f"Error checking Job status: {e}")
            return {"status": False, "error": str(e)}
    
    # Timeout
    if logger:
        logger.error(f"Ansible Job {job_name} timed out after {timeout}s")
    return {"status": False, "error": "Timeout"}


def get_job_logs(job_name: str, namespace: str, core_api=None) -> str:
    """Get logs from the Job's pod."""
    if core_api is None:
        core_api = client.CoreV1Api()
    
    try:
        # Find pod for this job
        pods = core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job-name={job_name}"
        )
        
        if pods.items:
            pod_name = pods.items[0].metadata.name
            logs = core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=50
            )
            return logs
        return "No pods found for job"
        
    except ApiException as e:
        return f"Error getting logs: {e}"


def run_host_registration(
    request_name: str,
    cluster_name: str = None,
    project_dir: str = None,
    namespace: str = JOB_NAMESPACE,
    logger=None
) -> Dict[str, Any]:
    """
    Run the host registration Ansible playbook.
    
    Args:
        request_name: Name of the ProvisioningRequest (used in job name)
        cluster_name: Name of the cluster being provisioned (for unique job name)
        project_dir: Path to project directory on management node
        namespace: Namespace for the Job
        logger: Logger instance
    
    Returns:
        dict with 'status' (bool) and details
    """
    # Apply default from environment variable
    project_dir = project_dir or DEFAULT_PROJECT_DIR
    
    # Use cluster_name for uniqueness to prevent conflicts during batch provisioning
    # If cluster_name not provided, fall back to request_name
    unique_id = cluster_name or request_name
    # Truncate and add short UUID for guaranteed uniqueness
    short_uuid = str(uuid.uuid4())[:8]
    job_name = f"ansible-{unique_id[:30]}-{short_uuid}"
    # Kubernetes job names must be lowercase and valid DNS
    job_name = job_name.lower().replace("_", "-")
    
    if logger:
        logger.info(f"Starting host registration for {request_name} (cluster: {cluster_name})")
    
    # Create the job
    result = create_ansible_job(
        job_name=job_name,
        playbook_path="site.yaml",
        project_dir=project_dir,
        namespace=namespace,
        logger=logger
    )
    
    if not result.get("status"):
        return result
    
    # Wait for completion
    result = wait_for_ansible_job(
        job_name=job_name,
        namespace=namespace,
        timeout=DEFAULT_TIMEOUT,
        logger=logger
    )
    
    return result

