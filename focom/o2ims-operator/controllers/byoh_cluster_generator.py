"""
BYOH Cluster Generator for O2IMS Operator

This module generates BYOH CAPI cluster resources from ProvisioningRequest parameters.
It replaces the Porch/PackageVariant approach with direct resource generation.
"""

import yaml
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


def generate_byoh_cluster_resources(
    cluster_name: str,
    masters: List[Dict],
    workers: List[Dict],
    k8s_version: str = "v1.32.0",
    namespace: str = "default",
    pod_cidr: str = "10.244.0.0/16",
    service_cidr: str = "10.128.0.0/12",
) -> List[Dict[str, Any]]:
    """
    Generate all BYOH CAPI resources needed for a cluster.
    
    Args:
        cluster_name: Name of the cluster to create
        masters: List of master node configurations [{hostId, hostName, hostIp}]
        workers: List of worker node configurations [{hostId, hostName, hostIp}]
        k8s_version: Kubernetes version (e.g., "v1.32.0")
        namespace: Kubernetes namespace for resources
        pod_cidr: Pod network CIDR
        service_cidr: Service network CIDR
    
    Returns:
        List of Kubernetes resource dictionaries
    """
    resources = []
    
    # Get control plane endpoint from first master
    if not masters:
        raise ValueError("At least one master node is required")
    
    first_master = masters[0]
    endpoint_ip = first_master.get("hostIp", first_master.get("hostName", ""))
    
    # 1. KubeadmConfigTemplate for workers
    resources.append(_generate_kubeadm_config_template(cluster_name, namespace))
    
    # 2. Cluster object
    resources.append(_generate_cluster(cluster_name, namespace, pod_cidr, service_cidr))
    
    # 3. ByoCluster infrastructure
    resources.append(_generate_byo_cluster(cluster_name, namespace, endpoint_ip))
    
    # 4. KubeadmControlPlane
    resources.append(_generate_kubeadm_control_plane(
        cluster_name, namespace, k8s_version, len(masters), endpoint_ip, masters
    ))
    
    # 5. ByoMachineTemplate for control plane
    resources.append(_generate_byo_machine_template_cp(
        cluster_name, namespace, masters
    ))
    
    # 6. Worker MachineDeployments and templates (one per worker for pinning)
    for worker in workers:
        resources.append(_generate_machine_deployment(
            cluster_name, namespace, k8s_version, worker
        ))
        resources.append(_generate_byo_machine_template_worker(
            cluster_name, namespace, worker
        ))
    
    # 7. Installer templates
    resources.append(_generate_installer_template(cluster_name, namespace, "cp"))
    resources.append(_generate_installer_template(cluster_name, namespace, "worker"))
    
    return resources


def _generate_kubeadm_config_template(cluster_name: str, namespace: str) -> Dict:
    """Generate KubeadmConfigTemplate for workers."""
    return {
        "apiVersion": "bootstrap.cluster.x-k8s.io/v1beta1",
        "kind": "KubeadmConfigTemplate",
        "metadata": {
            "name": f"{cluster_name}-md-base",
            "namespace": namespace
        },
        "spec": {
            "template": {
                "spec": {}
            }
        }
    }


def _generate_cluster(cluster_name: str, namespace: str, pod_cidr: str, service_cidr: str) -> Dict:
    """Generate Cluster object."""
    return {
        "apiVersion": "cluster.x-k8s.io/v1beta1",
        "kind": "Cluster",
        "metadata": {
            "labels": {
                "cni": f"{cluster_name}-crs-0",
                "crs": "true"
            },
            "name": cluster_name,
            "namespace": namespace
        },
        "spec": {
            "clusterNetwork": {
                "pods": {"cidrBlocks": [pod_cidr]},
                "serviceDomain": "cluster.local",
                "services": {"cidrBlocks": [service_cidr]}
            },
            "controlPlaneRef": {
                "apiVersion": "controlplane.cluster.x-k8s.io/v1beta1",
                "kind": "KubeadmControlPlane",
                "name": f"{cluster_name}-control-plane"
            },
            "infrastructureRef": {
                "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
                "kind": "ByoCluster",
                "name": cluster_name
            }
        }
    }


def _generate_byo_cluster(cluster_name: str, namespace: str, endpoint_ip: str) -> Dict:
    """Generate ByoCluster infrastructure object."""
    return {
        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
        "kind": "ByoCluster",
        "metadata": {
            "name": cluster_name,
            "namespace": namespace
        },
        "spec": {
            "bundleLookupBaseRegistry": "projects.registry.vmware.com/cluster_api_provider_bringyourownhost",
            "controlPlaneEndpoint": {
                "host": endpoint_ip,
                "port": 6443
            }
        }
    }


def _generate_kube_vip_manifest(endpoint_ip: str) -> str:
    """Generate kube-vip static pod manifest."""
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "kube-vip",
            "namespace": "kube-system"
        },
        "spec": {
            "containers": [{
                "args": ["manager"],
                "env": [
                    {"name": "cp_enable", "value": "true"},
                    {"name": "vip_arp", "value": "true"},
                    {"name": "vip_leaderelection", "value": "true"},
                    {"name": "vip_address", "value": endpoint_ip},
                    {"name": "vip_interface", "value": "{{ .DefaultNetworkInterfaceName }}"},
                    {"name": "vip_leaseduration", "value": "15"},
                    {"name": "vip_renewdeadline", "value": "10"},
                    {"name": "vip_retryperiod", "value": "2"}
                ],
                "image": "ghcr.io/kube-vip/kube-vip:v0.5.0",
                "imagePullPolicy": "IfNotPresent",
                "name": "kube-vip",
                "securityContext": {
                    "capabilities": {"add": ["NET_ADMIN", "NET_RAW"]}
                },
                "volumeMounts": [{
                    "mountPath": "/etc/kubernetes/admin.conf",
                    "name": "kubeconfig"
                }]
            }],
            "hostNetwork": True,
            "hostAliases": [{"hostnames": ["kubernetes"], "ip": "127.0.0.1"}],
            "volumes": [{
                "hostPath": {
                    "path": "/etc/kubernetes/admin.conf",
                    "type": "FileOrCreate"
                },
                "name": "kubeconfig"
            }]
        }
    }
    return yaml.dump(manifest, default_flow_style=False)


def _generate_kubeadm_control_plane(
    cluster_name: str, 
    namespace: str, 
    k8s_version: str,
    replicas: int,
    endpoint_ip: str,
    masters: List[Dict]
) -> Dict:
    """Generate KubeadmControlPlane object."""
    return {
        "apiVersion": "controlplane.cluster.x-k8s.io/v1beta1",
        "kind": "KubeadmControlPlane",
        "metadata": {
            "name": f"{cluster_name}-control-plane",
            "namespace": namespace
        },
        "spec": {
            "replicas": replicas,
            "version": k8s_version,
            "machineTemplate": {
                "infrastructureRef": {
                    "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
                    "kind": "ByoMachineTemplate",
                    "name": f"{cluster_name}-cp-template",
                    "namespace": namespace
                }
            },
            "kubeadmConfigSpec": {
                "clusterConfiguration": {
                    "apiServer": {
                        "certSANs": [
                            "localhost", "127.0.0.1", "0.0.0.0",
                            "host.docker.internal", endpoint_ip
                        ]
                    },
                    "controllerManager": {
                        "extraArgs": {"enable-hostpath-provisioner": "true"}
                    }
                },
                "initConfiguration": {
                    "nodeRegistration": {
                        "criSocket": "/var/run/containerd/containerd.sock",
                        "ignorePreflightErrors": [
                            "Swap",
                            "DirAvailable--etc-kubernetes-manifests",
                            "FileAvailable--etc-kubernetes-kubelet.conf"
                        ]
                    }
                },
                "joinConfiguration": {
                    "nodeRegistration": {
                        "criSocket": "/var/run/containerd/containerd.sock",
                        "ignorePreflightErrors": [
                            "Swap",
                            "DirAvailable--etc-kubernetes-manifests",
                            "FileAvailable--etc-kubernetes-kubelet.conf"
                        ]
                    }
                },
                "postKubeadmCommands": [
                    "curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.27.2/manifests/calico.yaml -o /root/calico.yaml",
                    "kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f /root/calico.yaml || true"
                ],
                "files": [{
                    "content": _generate_kube_vip_manifest(endpoint_ip),
                    "owner": "root:root",
                    "path": "/etc/kubernetes/manifests/kube-vip.yaml"
                }]
            }
        }
    }


def _generate_byo_machine_template_cp(
    cluster_name: str, 
    namespace: str, 
    masters: List[Dict]
) -> Dict:
    """Generate ByoMachineTemplate for control plane."""
    host_ids = [str(m.get("hostId", m.get("host_id", ""))) for m in masters]
    
    return {
        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
        "kind": "ByoMachineTemplate",
        "metadata": {
            "name": f"{cluster_name}-cp-template",
            "namespace": namespace
        },
        "spec": {
            "template": {
                "spec": {
                    "installerRef": {
                        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
                        "kind": "K8sInstallerConfigTemplate",
                        "name": f"{cluster_name}-cp-installer",
                        "namespace": namespace
                    },
                    "selector": {
                        "matchExpressions": [{
                            "key": "host-id",
                            "operator": "In",
                            "values": host_ids
                        }]
                    }
                }
            }
        }
    }


def _generate_machine_deployment(
    cluster_name: str,
    namespace: str,
    k8s_version: str,
    worker: Dict
) -> Dict:
    """Generate MachineDeployment for a worker."""
    host_id = worker.get("hostId", worker.get("host_id", ""))
    
    return {
        "apiVersion": "cluster.x-k8s.io/v1beta1",
        "kind": "MachineDeployment",
        "metadata": {
            "name": f"{cluster_name}-worker-{host_id}",
            "namespace": namespace
        },
        "spec": {
            "clusterName": cluster_name,
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "cluster.x-k8s.io/cluster-name": cluster_name,
                    "pool": f"worker-{host_id}"
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "cluster.x-k8s.io/cluster-name": cluster_name,
                        "pool": f"worker-{host_id}"
                    }
                },
                "spec": {
                    "clusterName": cluster_name,
                    "version": k8s_version,
                    "bootstrap": {
                        "configRef": {
                            "apiVersion": "bootstrap.cluster.x-k8s.io/v1beta1",
                            "kind": "KubeadmConfigTemplate",
                            "name": f"{cluster_name}-md-base"
                        }
                    },
                    "infrastructureRef": {
                        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
                        "kind": "ByoMachineTemplate",
                        "name": f"{cluster_name}-worker-{host_id}"
                    }
                }
            }
        }
    }


def _generate_byo_machine_template_worker(
    cluster_name: str,
    namespace: str,
    worker: Dict
) -> Dict:
    """Generate ByoMachineTemplate for a worker."""
    host_id = str(worker.get("hostId", worker.get("host_id", "")))
    
    return {
        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
        "kind": "ByoMachineTemplate",
        "metadata": {
            "name": f"{cluster_name}-worker-{host_id}",
            "namespace": namespace
        },
        "spec": {
            "template": {
                "spec": {
                    "installerRef": {
                        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
                        "kind": "K8sInstallerConfigTemplate",
                        "name": f"{cluster_name}-worker-installer",
                        "namespace": namespace
                    },
                    "selector": {
                        "matchLabels": {
                            "host-id": host_id
                        }
                    }
                }
            }
        }
    }


def _generate_installer_template(cluster_name: str, namespace: str, role: str) -> Dict:
    """Generate K8sInstallerConfigTemplate."""
    return {
        "apiVersion": "infrastructure.cluster.x-k8s.io/v1beta1",
        "kind": "K8sInstallerConfigTemplate",
        "metadata": {
            "name": f"{cluster_name}-{role}-installer",
            "namespace": namespace
        },
        "spec": {
            "template": {
                "spec": {
                    "bundleRepo": "projects.registry.vmware.com/cluster_api_provider_bringyourownhost",
                    "bundleType": "k8s"
                }
            }
        }
    }


def resources_to_yaml(resources: List[Dict]) -> str:
    """Convert list of resources to multi-document YAML string."""
    yaml_docs = []
    for resource in resources:
        yaml_docs.append(yaml.dump(resource, default_flow_style=False))
    return "---\n".join(yaml_docs)
