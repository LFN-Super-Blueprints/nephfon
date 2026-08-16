# Provisioning

Recommended path: edit `input.json`, then `kubectl apply -f examples/focom-all-clusters.yaml`. Architecture: [architecture.md](architecture.md).

# Cluster Configuration Guide

This guide explains how to configure clusters and hosts for provisioning.

---

## input.json Structure

The `input.json` file is the central configuration for defining hosts and clusters.

### Complete Example

```json
{
  "k8s_version": "1.32.0",
  "hosts": [
    {
      "host_id": 1,
      "host_name": "server-1",
      "host_ip": "192.168.1.101",
      "host_user": "ubuntu",
      "host_pwd": ""
    },
    {
      "host_id": 2,
      "host_name": "server-2",
      "host_ip": "192.168.1.102",
      "host_user": "ubuntu",
      "host_pwd": ""
    },
    {
      "host_id": 3,
      "host_name": "server-3",
      "host_ip": "192.168.1.103",
      "host_user": "ubuntu",
      "host_pwd": ""
    }
  ],
  "clusters": [
    {
      "cluster_name": "edge",
      "cluster_type": "ran",
      "pod_cidr": "10.245.0.0/16",
      "service_cidr": "10.97.0.0/12",
      "cluster_masters": [
        { "host_id": 1 }
      ],
      "cluster_workers": []
    },
    {
      "cluster_name": "core",
      "cluster_type": "core",
      "pod_cidr": "10.246.0.0/16",
      "service_cidr": "10.98.0.0/12",
      "cluster_masters": [
        { "host_id": 2 }
      ],
      "cluster_workers": [
        { "host_id": 3 }
      ]
    }
  ]
}
```

---

## Field Reference

### Global Settings

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `k8s_version` | string | No | Kubernetes version (default: 1.32.0) |

### Host Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `host_id` | integer | ✅ | Unique identifier for the host |
| `host_name` | string | ✅ | Hostname (used for ByoHost registration) |
| `host_ip` | string | ✅ | IP address or FQDN for SSH access |
| `host_user` | string | ✅ | SSH username |
| `host_pwd` | string | No | SSH password (leave empty for key-based auth) |

### Cluster Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cluster_name` | string | ✅ | Unique cluster name (DNS-compatible) |
| `cluster_type` | string | No | `"core"` or `"ran"` — triggers node pre-requisites (see [README](../README.md)) |
| `pod_cidr` | string | No | Pod network CIDR (default: `10.244.0.0/16`) |
| `service_cidr` | string | No | Service network CIDR (default: `10.96.0.0/12`) |
| `cluster_masters` | array | ✅ | List of master nodes (reference by host_id) |
| `cluster_workers` | array | No | List of worker nodes (can be empty) |

---

## Cluster Topologies

### Single Node (Development)

```json
{
  "cluster_name": "dev",
  "cluster_masters": [
    { "host_id": 1 }
  ],
  "cluster_workers": []
}
```

### 1 Master + 2 Workers

```json
{
  "cluster_name": "production",
  "cluster_masters": [
    { "host_id": 1 }
  ],
  "cluster_workers": [
    { "host_id": 2 },
    { "host_id": 3 }
  ]
}
```

### HA Cluster (3 Masters + 3 Workers)

```json
{
  "cluster_name": "ha-cluster",
  "cluster_masters": [
    { "host_id": 1 },
    { "host_id": 2 },
    { "host_id": 3 }
  ],
  "cluster_workers": [
    { "host_id": 4 },
    { "host_id": 5 },
    { "host_id": 6 }
  ]
}
```

---

## Supported Kubernetes Versions

| Version | Status |
|---------|--------|
| v1.34.0 | ✅ Supported |
| v1.33.0 | ✅ Supported |
| v1.32.0 | ✅ Supported (Default) |
| v1.31.0 | ✅ Supported |
| v1.30.0 | ✅ Supported |

---

## Validation Rules

| Rule | Description |
|------|-------------|
| **Unique host_id** | Each host must have a unique ID |
| **Unique cluster_name** | Each cluster must have a unique name |
| **Odd masters** | HA clusters must have 1, 3, or 5 masters |
| **No host reuse** | A host can only belong to one cluster |
| **Valid DNS name** | cluster_name must be DNS-compatible |

---

## SSH Authentication

### Option 1: SSH Key (Recommended)

1. Ensure SSH keys are set up:
   ```bash
   ssh-copy-id ubuntu@192.168.1.101
   ```

2. Leave `host_pwd` empty in input.json:
   ```json
   {
     "host_user": "ubuntu",
     "host_pwd": ""
   }
   ```

### Option 2: Password Authentication

```json
{
  "host_user": "ubuntu",
  "host_pwd": "your-password"
}
```

> [!WARNING]
> Password authentication is less secure. Use SSH keys in production.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Duplicate host_id | Each host must have unique ID |
| Even number of masters | Use 1, 3, or 5 masters |
| Same host in multiple clusters | Each host can only be in one cluster |
| Invalid cluster name | Use lowercase, no spaces, DNS-compatible |
| Wrong IP/hostname | Verify SSH access: `ssh user@host` |

---

## Quick Validation

Test your configuration before provisioning:

```bash
# Validate JSON syntax
python3 -c "import json; json.load(open('input.json'))"

# Test SSH to each host
ssh ubuntu@192.168.1.101 "hostname"
```


---

# Alternate methods

> **Note:** The standard and recommended way to create clusters is using `input.json` + `focom-all-clusters.yaml`. See the [README](../README.md) for details.
>
> This document describes **alternative provisioning methods** for advanced use cases. These methods are supported by the FOCOM and O2IMS operators but are not the primary workflow.

---

## Table of Contents

- [Standard Method (Recommended)](#standard-method-recommended)
- [Method 1: Selected Clusters](#method-1-selected-clusters)
- [Method 2: Template-Based (FOCOM)](#method-2-template-based-focom)
- [Method 3: Direct O2IMS Request](#method-3-direct-o2ims-request)
- [Method 4: Scale Cluster Workers](#method-4-scale-cluster-workers)
- [Comparison Table](#comparison-table)

---

## Standard Method (Recommended)

The simplest and most reliable way to provision clusters:

1. Define all hosts and clusters in `input.json`
2. Apply the batch request:

```bash
kubectl apply -f examples/focom-all-clusters.yaml
```

This reads **all** cluster definitions from `input.json` and creates them automatically. See `README.md` for full documentation.

---

## Method 1: Selected Clusters

**Use case:** You have multiple clusters defined in `input.json` but only want to create specific ones (not all).

### How It Works

Instead of `allClusters: true`, you provide a `clusterNames` array with the names of the clusters you want to create. The controller will look up each cluster in `input.json` and create only those.

### YAML Template

Create a file (e.g., `my-selected-clusters.yaml`):

```yaml
apiVersion: focom.nephio.org/v1alpha1
kind: FocomProvisioningRequest
metadata:
  name: create-selected-clusters
  namespace: default
spec:
  # Specify which clusters to create (must exist in input.json)
  clusterNames:
    - "ran"
    - "core"

  # Optional: override target namespace
  # oCloudNamespace: "default"
```

### How to Use

```bash
# Step 1: Make sure the clusters are defined in input.json
cat input.json | jq '.clusters[].cluster_name'
# Output: "ran", "core", "edge"

# Step 2: Create only specific clusters
kubectl apply -f my-selected-clusters.yaml

# Step 3: Monitor
kubectl get fpr -w
kubectl get clusters -w
```

### Key Points

- Cluster names in `clusterNames` **must match** `cluster_name` in `input.json`
- CIDRs, cluster_type, and host assignments all come from `input.json`
- If a cluster name doesn't exist in `input.json`, it will fail with an error

---

## Method 2: Template-Based (FOCOM)

**Use case:** You want to create a single cluster with all parameters specified directly in the YAML, **without relying on `input.json`**.

### How It Works

You provide `templateName` and `templateParameters` directly in the FOCOM request. The controller uses these parameters as-is to create the O2IMS ProvisioningRequest.

### YAML Template

Create a file (e.g., `my-cluster-request.yaml`):

```yaml
apiVersion: focom.nephio.org/v1alpha1
kind: FocomProvisioningRequest
metadata:
  name: my-cluster-request
  namespace: default
spec:
  oCloudNamespace: "default"
  templateName: "byoh-workload-cluster"
  templateParameters:
    clusterName: myCluster
    k8sVersion: "v1.32.0"
    clusterProvisioner: byoh
    clusterType: "core"           # "core", "ran", or omit for vanilla
    podCidr: "10.245.0.0/16"      # Custom Pod CIDR
    serviceCidr: "10.97.0.0/12"   # Custom Service CIDR
    hosts:
      masters:
        - hostId: 1
          hostName: server-1
          hostIp: "192.168.1.101"
      workers:
        - hostId: 2
          hostName: server-2
          hostIp: "192.168.1.102"
```

### How to Use

```bash
# Step 1: Edit the YAML with your actual host details
vi my-cluster-request.yaml

# Step 2: Apply
kubectl apply -f my-cluster-request.yaml

# Step 3: Monitor
kubectl get fpr -w
kubectl get pr -w
kubectl get clusters -w

# Step 4: Access the cluster
kubectl get secret myCluster-kubeconfig -o jsonpath='{.data.value}' | base64 -d > myCluster.kubeconfig
kubectl --kubeconfig=myCluster.kubeconfig get nodes
```

### Key Points

- All parameters are **hardcoded** in the YAML — nothing comes from `input.json`
- `hostId` values **must still match** entries in `input.json` for Ansible to work
- You must specify `podCidr` and `serviceCidr` manually to avoid CIDR conflicts
- Creating multiple clusters requires multiple YAML files

### When to Use This

- You need a one-off cluster that's not defined in `input.json`
- You're testing specific parameter combinations
- You want explicit control over every parameter

---

## Method 3: Direct O2IMS Request

**Use case:** You want to bypass the FOCOM layer entirely and create a cluster directly via the O2IMS operator.

### How It Works

You create a `ProvisioningRequest` (O2IMS CRD) directly, bypassing the FOCOM operator. The O2IMS operator processes it and creates the BYOH CAPI resources.

### YAML Template

Create a file (e.g., `direct-cluster.yaml`):

```yaml
apiVersion: o2ims.provisioning.oran.org/v1alpha1
kind: ProvisioningRequest
metadata:
  name: direct-cluster-request
  namespace: default
spec:
  name: "directCluster"
  description: "Cluster created directly via O2IMS"
  templateName: "byoh-workload-cluster"
  templateVersion: "v1.0.0"
  templateParameters:
    clusterName: directCluster
    k8sVersion: "v1.32.0"
    clusterProvisioner: byoh
    clusterType: "core"           # "core", "ran", or omit for vanilla
    podCidr: "10.248.0.0/16"      # Custom Pod CIDR
    serviceCidr: "10.100.0.0/12"  # Custom Service CIDR
    hosts:
      masters:
        - hostId: 1
          hostName: server-1
          hostIp: "192.168.1.101"
      workers:
        - hostId: 2
          hostName: server-2
          hostIp: "192.168.1.102"
```

### How to Use

```bash
# Apply directly (no FOCOM involved)
kubectl apply -f direct-cluster.yaml

# Monitor via O2IMS
kubectl get provisioningrequests -w
kubectl get clusters -w
```

### Key Points

- **Bypasses FOCOM** — no batch support, no status rollup, no orchestration
- Same parameters as the template-based method
- Useful for debugging O2IMS operator behavior directly
- Not recommended for production use

---

## Method 4: Scale Cluster Workers

**Use case:** You want to add or remove worker nodes from an existing cluster.

### How It Works

The FOCOM operator patches the `MachineDeployment` for the named cluster, changing the replica count to match `targetWorkerCount`.

### YAML Template

Create a file (e.g., `scale-cluster.yaml`):

```yaml
apiVersion: focom.nephio.org/v1alpha1
kind: FocomProvisioningRequest
metadata:
  name: scale-ran-cluster
spec:
  # Must be "scale" to trigger the scale handler
  operation: scale

  # Which cluster to scale
  clusterName: "ran"

  # Target number of worker nodes
  targetWorkerCount: 2
```

### How to Use

```bash
# Step 1: Make sure the cluster exists and has a MachineDeployment
kubectl get machinedeployments

# Step 2: Update input.json with the new worker hosts
vi input.json
# Add new host entries and add them to cluster_workers

# Step 3: Apply the scale request
kubectl apply -f scale-cluster.yaml

# Step 4: Monitor
kubectl get machines -w
```

### Prerequisites

- The cluster **must already exist** and be in `Provisioned` state
- The cluster **must have a MachineDeployment** (i.e., it was originally created with workers, or has at least one worker defined)
- New worker hosts must be defined in `input.json` and reachable via SSH
- If `targetWorkerCount` is omitted, the controller reads the worker count from `input.json`

### Limitations

- Only scales **worker nodes**, not control plane nodes
- Cannot scale a cluster that has 0 workers (no MachineDeployment exists)
- Scaling down removes workers but doesn't clean up the host registration

---

## Comparison Table

| Method | Source of Config | Multi-Cluster | FOCOM Layer | Best For |
|--------|-----------------|---------------|------------|----------|
| **Standard (`input.json`)** | `input.json` | ✅ All at once | ✅ Yes | Production deployments |
| **Selected Clusters** | `input.json` | ✅ Selected | ✅ Yes | Partial re-deploys |
| **Template-Based** | Inline YAML | ❌ One at a time | ✅ Yes | One-off clusters |
| **Direct O2IMS** | Inline YAML | ❌ One at a time | ❌ Bypassed | Debugging |
| **Scale** | YAML + input.json | ❌ One cluster | ✅ Yes | Adding workers |
