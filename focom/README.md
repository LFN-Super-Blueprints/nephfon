# Multi-Cluster LCM with O2IMS Support

Further reading: [architecture](docs/architecture.md) · [provisioning](docs/provisioning.md) · [testing and troubleshooting](docs/operations.md)

A Kubernetes-native Multi-Cluster Lifecycle Management (LCM) system with O-RAN O2 IMS support for provisioning bare-metal Kubernetes clusters.

## NOTE: After installing this mgmt.sh script you need to install Nephio on this cluster.
You can use this:
```
wget -O - https://raw.githubusercontent.com/nephio-project/test-infra/main/e2e/provision/init.sh | \
sudo NEPHIO_DEBUG=false \
NEPHIO_BRANCH=main \
NEPHIO_USER=$(whoami) \
DOCKERHUB_USERNAME=username \
DOCKERHUB_TOKEN=token \
K8S_CONTEXT=$(kubectl config current-context) \
bash 
```
**Reference**: https://docs.nephio.org/docs/guides/install-guides/

## 📋 Project Overview

This project implements automated provisioning of Kubernetes clusters on Linux servers using:

- **CAPI BYOH** (Cluster API - Bring Your Own Host) for bare-metal cluster provisioning
- **O2IMS Operator** for O-RAN O2 Infrastructure Management Service compliant cluster lifecycle
- **FOCOM Operator** for SMO/Orchestrator integration interface

### Key Features

- ✅ Multi-cluster lifecycle management from a single management plane
- ✅ O2IMS-style ProvisioningRequest API for cluster creation
- ✅ FOCOM interface for SMO/Orchestrator integration
- ✅ Bare-metal Kubernetes provisioning (no cloud dependency)
- ✅ Host pinning for deterministic cluster placement
- ✅ Status reporting through the provisioning chain
- ✅ Custom Pod/Service CIDR per cluster (no IP conflicts)
- ✅ Cluster-specific pre-requisites (CORE vs RAN node configuration)

---

## 🏗️ Architecture

```
                           SMO / Orchestrator
                                   │
                                   │ FocomProvisioningRequest
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    BYOH Management Cluster                   │
│                                                              │
│   ┌─────────────────┐       ┌─────────────────┐              │
│   │  FOCOM Operator │──────▶│  O2IMS Operator │              │
│   │ (focom-system)  │       │ (o2ims-system)  │              │
│   └─────────────────┘       └────────┬────────┘              │
│           │                          │                       │
│           │                          │ Creates CAPI Resources│
│           │                          ▼                       │
│           │                 ┌─────────────────┐              │
│           │                 │ BYOH Controller │              │
│           │                 │  (byoh-system)  │              │
│           │                 └────────┬────────┘              │
└───────────┼──────────────────────────┼───────────────────────┘
            │                          │
            │                          │ Provisions on bare-metal
            │                          ▼
            │              ┌───────────────────────┐
            │              │   Workload Clusters   │
            │              │  ┌─────┐   ┌─────┐    │
            │              │  │core │   │edge │    │
            │              │  └─────┘   └─────┘    │
            │              └───────────────────────┘
            │
     Creates ProvisioningRequest
```

### Component Roles

| Component | Role | Input | Output |
|-----------|------|-------|--------|
| **FOCOM Operator** | SMO-facing interface | `FocomProvisioningRequest` | Creates `ProvisioningRequest` |
| **O2IMS Operator** | Cluster lifecycle manager | `ProvisioningRequest` | Creates BYOH CAPI resources |
| **BYOH Controller** | Bare-metal provisioner | CAPI resources | Kubernetes cluster on hosts |

---

## 🔄 Workflow

### Fully Automated Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUTOMATED PROVISIONING FLOW                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Clone Repo          2. Run mgmt.sh         3. Edit Configs              │
│  ─────────────          ─────────────          ─────────────                │
│  git clone ...    ──▶   ./mgmt.sh        ──▶   vi input.json                │
│                         (~30 mins)              vi examples/focom-...yaml   │
│                                                                             │
│  4. Apply Request       5. Watch Magic         6. Cluster Ready!            │
│  ───────────────        ─────────────          ──────────────               │
│  kubectl apply    ──▶   Auto-Ansible     ──▶   kubectl get clusters         │
│  -f focom-...yaml       Auto-CAPI              ✅ edge: Ready               |
│                         (~5-10 mins)                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Management Cluster Setup (One-time, ~30 mins)

```bash
./mgmt.sh
```

This installs:
- Kubernetes management cluster
- CAPI + BYOH provider
- O2IMS Operator
- FOCOM Operator
- Ansible Runner Image (for automation)

### Phase 2: Configure Host Details

Edit `input.json` with your host and cluster information:
```json
{
  "k8s_version": "1.32.0",
  "hosts": [
    {
      "host_id": 1,
      "host_name": "server-1",
      "host_ip": "10.x.x.x",
      "host_user": "ubuntu"
    }
  ],
  "clusters": [
    {
      "cluster_name": "my-cluster",
      "cluster_type": "core",
      "pod_cidr": "10.245.0.0/16",
      "service_cidr": "10.97.0.0/12",
      "cluster_masters": [{ "host_id": 1 }],
      "cluster_workers": []
    }
  ]
}
```

Edit `examples/focom-all-clusters.yaml` if you need to change the target namespace (defaults to `default`).

> [!IMPORTANT]
> All cluster and host details come from `input.json`. See [docs/provisioning.md](docs/provisioning.md) for detailed configuration options.

### Phase 3: Create Cluster (Fully Automated!)

```bash
kubectl apply -f examples/focom-all-clusters.yaml
```

**What happens automatically:**
1. FOCOM creates ProvisioningRequest
2. O2IMS checks if hosts are registered
3. If not → **Ansible Job runs automatically** to prepare hosts
4. BYOH CAPI resources are created
5. Cluster is provisioned

### Phase 4: Monitor & Access

```bash
# Watch provisioning status
kubectl get focomprovisioningrequests -w
kubectl get provisioningrequests -w
kubectl get clusters -w

# Access workload cluster
kubectl get secret <cluster>-kubeconfig -o jsonpath='{.data.value}' | base64 -d > cluster.kubeconfig
kubectl --kubeconfig=cluster.kubeconfig get nodes
```

---

## 🎯 How This Completes the LCM O2IMS Objective

### Objective: Multi-Cluster LCM with O2IMS Support

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| **Multi-Cluster Management** | Single management plane provisions multiple workload clusters | ✅ |
| **Lifecycle Management** | Create, monitor, delete clusters via ProvisioningRequest | ✅ |
| **O2IMS Interface** | `ProvisioningRequest` CRD with status reporting | ✅ |
| **Bare-Metal Support** | CAPI BYOH provisions on Linux servers | ✅ |
| **Orchestrator Integration** | FOCOM provides SMO-facing interface | ✅ |
| **Automated Host Registration** | Ansible runs automatically if hosts not registered | ✅ |

### O2IMS ProvisioningRequest Lifecycle

```
                    ProvisioningRequest Created
                              │
                              ▼
                     ┌─────────────────┐
                     │    PENDING      │
                     └────────┬────────┘
                              │
               O2IMS checks if hosts registered
                              │
         ┌────────────────────┴────────────────────┐
         │                                         │
    Not Registered                            Registered
         │                                         │
         ▼                                         │
┌─────────────────┐                                │
│  PROGRESSING    │                                │
│ (Ansible Job)   │                                │
└────────┬────────┘                                │
         │                                         │
         └────────────────────┬────────────────────┘
                              │
                     BYOH provisions cluster
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     │                     ▼
┌─────────────┐               │            ┌─────────────┐
│  FULFILLED  │               │            │   FAILED    │
└─────────────┘               │            └─────────────┘
                              │
                     On delete request
                              │
                              ▼
                     ┌─────────────────┐
                     │   DELETING      │
                     └─────────────────┘
```

---

## 📁 Project Structure

```
focom/
├── README.md                 # This guide
├── docs/
│   ├── architecture.md       # Flow, CRDs, O-RAN/CAPI mapping
│   ├── provisioning.md       # input.json and alternate methods
│   └── operations.md         # Tests and recovery
├── mgmt.sh                   # Management cluster setup
├── site.yaml                 # Ansible host registration
├── input.json                # Host and cluster inventory
├── o2ims-operator/
├── focom-operator/
├── examples/
└── templates/
```

---

## 🚀 Getting Started

### Prerequisites

- A Linux server (Ubuntu 20.04+ recommended) for the management cluster
- SSH access to bare-metal servers that will become workload cluster nodes
- Minimum 4 CPU, 8GB RAM for management cluster

### Step 1: Setup Management Cluster

```bash
# Clone the repository
git clone https://github.com/ios-mcn-smo/byoh-nephio.git
cd byoh-nephio

# Run setup script (~30 mins)
# Paths are automatically configured!
./mgmt.sh
```

This installs: Kubernetes, CAPI + BYOH provider, O2IMS Operator, FOCOM Operator, and Ansible Runner.

---

## 📘 Method 1: Batch Provisioning with input.json (Recommended)

**Best for:** Creating multiple clusters at once with minimal configuration.

### Step 1: Configure Host Inventory

Edit `input.json` with your bare-metal server details. This is the **single source of truth** for all cluster configurations:

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
      "cluster_name": "ran",
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

### input.json Field Reference

#### Host Fields

| Field | Required | Description |
|-------|----------|-------------|
| `host_id` | Yes | Unique numeric ID for the host |
| `host_name` | Yes | Hostname (will be set on the server) |
| `host_ip` | Yes | IP address of the bare-metal server |
| `host_user` | Yes | SSH username for Ansible access |
| `host_pwd` | No | SSH password (empty = key-based auth) |

#### Cluster Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `cluster_name` | Yes | — | Name of the cluster |
| `cluster_type` | No | `""` (none) | `"core"` or `"ran"` — triggers node pre-requisites (see below) |
| `pod_cidr` | No | `10.244.0.0/16` | Pod network CIDR for this cluster |
| `service_cidr` | No | `10.96.0.0/12` | Service network CIDR for this cluster |
| `cluster_masters` | Yes | — | List of master nodes (`host_id` references) |
| `cluster_workers` | No | `[]` | List of worker nodes (`host_id` references) |

### Custom CIDR Configuration

Each cluster can have its own unique Pod and Service CIDR to **prevent IP conflicts** when multiple clusters exist on the same network.

- If you specify `pod_cidr` and `service_cidr` → your custom values are used
- If you omit them → defaults are used (`10.244.0.0/16` and `10.96.0.0/12`)

**Example — 3 clusters with unique CIDRs:**
```json
"clusters": [
  { "cluster_name": "ran-1",  "pod_cidr": "10.245.0.0/16", "service_cidr": "10.97.0.0/12" },
  { "cluster_name": "ran-2",  "pod_cidr": "10.247.0.0/16", "service_cidr": "10.99.0.0/12" },
  { "cluster_name": "core",   "pod_cidr": "10.246.0.0/16", "service_cidr": "10.98.0.0/12" }
]
```

> [!IMPORTANT]
> When running multiple clusters on the same network, always assign **unique CIDRs** to each cluster. Overlapping CIDRs will cause IP conflicts between clusters.

### Cluster-Specific Pre-requisites

The `cluster_type` field controls what pre-requisites are applied to the cluster nodes during provisioning:

| Cluster Type | Pre-requisites Applied |
|-------------|------------------------|
| `"core"` | Increased inotify limits (`max_user_watches=524288`, `max_user_instances=512`, `file-max=2097152`) + containerd sandbox image fix (`pause:3.3`) — prevents UPF pod initialization issues |
| `"ran"` | Hugepages allocation (20 × 1Gi) — required for high-performance RAN workloads |
| Not specified | No extra pre-requisites — creates a vanilla Kubernetes cluster |

**How it works:**
1. You set `cluster_type` in `input.json` (e.g., `"cluster_type": "ran"`)
2. When the Ansible playbook (`site.yaml`) runs, it detects each host's cluster type
3. It applies the correct pre-requisites based on the type
4. If `cluster_type` is not specified, the host gets a standard setup

### Step 2: Create All Clusters

```bash
# Create ALL clusters defined in input.json with a single command!
kubectl apply -f examples/focom-all-clusters.yaml
```

That's it! The controller will:
1. Read all cluster definitions from `input.json`
2. Validate each cluster configuration
3. Automatically register hosts via Ansible
4. Create BYOH CAPI resources for each cluster
5. Provision all clusters

### Step 3: Monitor Progress

```bash
# Watch FOCOM request status
kubectl get fpr -w

# Watch individual provisioning requests
kubectl get pr -w

# Watch cluster status
kubectl get clusters -w
```

### Step 4: Access Workload Clusters

```bash
# Get kubeconfig for a specific cluster
kubectl get secret edge-cluster-kubeconfig -o jsonpath='{.data.value}' | base64 -d > edge.kubeconfig
kubectl --kubeconfig=edge.kubeconfig get nodes
```

---

## 🔄 Advanced Provisioning Methods

The `input.json` + `focom-all-clusters.yaml` approach covers most use cases. For advanced scenarios (selected clusters, template-based, direct O2IMS, scaling), see [docs/provisioning.md](docs/provisioning.md#alternate-methods).

---

## 🧹 Cleanup & Troubleshooting

```bash
# Delete a cluster
kubectl delete fpr my-cluster-request

# Delete all clusters
kubectl delete fpr --all
```

For recovery from failed attempts, proper cluster deletion with node cleanup, and common error fixes, see [docs/operations.md](docs/operations.md).

---

## ✅ Tested Results

| Test | Result |
|------|--------|
| O2IMS Operator deployment | ✅ Running |
| FOCOM Operator deployment | ✅ Running |
| Host registration | ✅ Registered |
| Cluster creation (batch via `input.json`) | ✅ `core` + `ran` clusters provisioned |
| Custom CIDR per cluster | ✅ Each cluster has unique Pod/Service CIDRs |
| CORE pre-requisites (inotify + sandbox) | ✅ Applied only to CORE nodes |
| RAN pre-requisites (hugepages) | ✅ Applied only to RAN nodes |
| Workload cluster access | ✅ Nodes Ready |

---

## 📄 License

Apache License 2.0
