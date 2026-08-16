# Nephio Deployment Management — OAI-RAN & SD-Core

Deploy OAI 5G RAN and Aether SD-Core on real Kubernetes clusters using Nephio's intent-based automation.

## Architecture

```
                    ┌──────────────────────────────────────────┐
                    │        Nephio Management Cluster         │
                    │     Porch · IPAM · Controllers           │
                    │                                          │
                    │  ┌─────────────────────────────────────┐ │
                    │  │  nephio-workload-blueprints (Git)   │ │
                    │  │  Upstream repo with ALL packages:   │ │
                    │  │  baseline, networking, OAI-RAN,     │ │
                    │  │  SD-Core                            │ │
                    │  └─────────────────────────────────────┘ │
                    └──────────┬────────────────┬──────────────┘
                               │                │
                    ┌──────────▼───┐    ┌───────▼───────────┐
                    │ Cluster: ran │    │ Cluster: core     │
                    │              │    │                   │
                    │ OAI-RAN      │    │ SD-Core 5G        │
                    │  • CUCP      │    │  • AMF  • SMF     │
                    │  • CUUP      │    │  • UPF  • NRF     │
                    │  • DU        │    │  • UDR  • UDM     │
                    │  • Operators │    │  • AUSF • PCF     │
                    │              │    │  • NSSF • WebUI   │
                    │              │    │  • MongoDB, Kafka │
                    └──────────────┘    └───────────────────┘
```

## Repository Structure

```
nephio-deployment-mgmt/
├── README.md
├── clusterconfig/
│   ├── ran-clustercontext.yaml          ClusterContext for ran cluster
│   ├── ran-workloadcluster.yaml         WorkloadCluster for ran cluster
│   ├── core-clustercontext.yaml         ClusterContext for core cluster
│   ├── core-workloadcluster.yaml        WorkloadCluster for core cluster
│   ├── rootsync-ran.yaml                RootSync for ran cluster
│   └── rootsync-core.yaml               RootSync for core cluster
├── repositories/
│   ├── upstream-repos.yaml              Blueprint repo registration
│   ├── ran-downstream-repo.yaml         RAN cluster deployment repo
│   └── core-downstream-repo.yaml        Core cluster deployment repo
├── prerequisites/
│   ├── oai-ran/
│   │   ├── networks-ran.yaml            All networks for OAI-RAN (self-contained)
│   │   ├── ipprefixes-ran.yaml          IP allocations for ran cluster
│   │   └── vlanindex-ran.yaml           VLANIndex for ran cluster
│   └── sd-core/
│       ├── networks-core.yaml           All networks for SD-Core (self-contained)
│       ├── ipprefixes-core.yaml         IP allocations for core cluster + DNN pool
│       └── vlanindex-core.yaml          VLANIndex for core cluster
├── packagevariants/
│   ├── baseline/
│   │   ├── baseline-ran.yaml            Baseline for ran cluster
│   │   └── baseline-core.yaml           Baseline for core cluster
│   ├── addons/
│   │   ├── addons-ran.yaml              Addons for ran cluster
│   │   └── addons-core.yaml             Addons for core cluster
│   ├── networking/
│   │   ├── networking-ran.yaml          Multus CNI for ran cluster
│   │   ├── networking-core.yaml         Multus CNI for core cluster
│   │   ├── vlan-agent-ran.yaml          VLAN agent for ran cluster
│   │   └── vlan-agent-core.yaml         VLAN agent for core cluster
│   ├── oai-ran/
│   │   └── oai-ran-pv.yaml             All OAI-RAN PackageVariants
│   └── sdcore/
│       └── sdcore-pv.yaml              CP + Operator + UPF + AMF + SMF
└── nad-master-fn/
    ├── main.go                          KRM function source code
    ├── go.mod / go.sum                  Go module
    ├── Dockerfile                       Multi-stage Docker build
    └── README.md                        Function documentation
```

---

## Host Networking Modes (`vlan` vs `nic`)

Secondary interfaces for 5G NFs (N2, N3, N4, E1, F1, …) need a host-side attachment.
This project supports **two selectable modes**. Pick one per NF via `networking-mode`
in the NF PackageVariants (not in the vlan-agent PackageVariant).

```
                    ┌─────────────────────────────┐
                    │  networking-mode in NF PV   │
                    └─────────────┬───────────────┘
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
         mode: vlan                              mode: nic
              │                                       │
    NAD master = ens4f0.<vlanID>             NAD master = eno49 (raw NIC)
              │                                       │
         vlan-agent creates                     no VLAN sub-interface
         ens4f0.<vlanID> on nodes               needed on the node
              │                                       │
         pod attaches via VLAN lane          pod attaches to physical NIC
```

| Mode | NAD `master` example | Host requirement | Best for |
|---|---|---|---|
| **`vlan`** (default) | `"ens4f0.6"` | `vlan-agent` + one trunk NIC | Nephio-native flow; many logical interfaces share one physical NIC |
| **`nic`** | `"eno49"` | That physical NIC exists on the node | Direct physical NIC per 3GPP interface (no VLAN layer) |

### Where to set `networking-mode`

| File | Role |
|---|---|
| `packagevariants/oai-ran/oai-ran-pv.yaml` | RAN NFs (CUCP, CUUP, DU) |
| `packagevariants/sdcore/sdcore-pv.yaml` | Core NFs (UPF, AMF, SMF) |
| `packagevariants/networking/vlan-agent-*.yaml` | Node VLAN creator only — **no** `networking-mode` here |

### Mode `vlan` — Nephio native (Interface → VLAN → NIC)

1. Set the **same** trunk NIC in both places:
   ```yaml
   # clusterconfig/ran-workloadcluster.yaml  (and core-…)
   spec:
     masterInterface: ens4f0

   # packagevariants/networking/vlan-agent-ran.yaml  (and vlan-agent-core.yaml)
   master-interface: ens4f0
   vlan-range: "2 3 4 5 6"
   ```
2. In each NF PackageVariant:
   ```yaml
   networking-mode: vlan
   # n*-interface / e1-interface / … are ignored in this mode
   ```
3. Deploy order: Multus → vlan-agent (wait Running) → NF PackageVariants.

**Flow:** `Interface (attachmentType: vlan)` → VLANClaim (`vlanID`) →
nad-fn writes `master: <masterInterface>.<vlanID>` → `nad-master-fn` leaves it
unchanged → vlan-agent creates that sub-interface on every node → Multus attaches.

**Verify:**
```bash
kubectl get net-attach-def -A -o yaml | grep master
# expect: "master": "ens4f0.6"

ip link show | grep ens4f0
# expect: ens4f0.2, ens4f0.3, …
```

### Mode `nic` — direct physical NIC (no VLAN)

1. In each NF PackageVariant, set mode and per-interface NICs:
   ```yaml
   networking-mode: nic
   n3-interface: eno49
   n4-interface: eno50
   n6-interface: ens1f0
   ```
2. vlan-agent is **not required** (harmless if left running).
3. Deploy order: Multus → NF PackageVariants.

**Flow:** nad-fn may still emit a VLAN-style master first → `nad-master-fn`
overwrites each NAD `master` with the mapped physical NIC → Multus attaches
directly to that NIC.

**Verify:**
```bash
kubectl get net-attach-def -A -o yaml | grep master
# expect: "master": "eno49"   (no .<vlanID> suffix)
```

### Switching modes

Change `networking-mode` in the NF PackageVariant, re-apply it, and approve /
wait for Porch to re-render. Modes can differ per NF if needed (e.g. UPF on
`vlan`, DU on `nic`).

---

## Custom KRM Function: `nad-master-fn`

A custom KRM function that implements the mode switch above. It is the **last**
step in every multi-NIC NF blueprint pipeline
(`docker.io/rehanfazal47/nad-master-fn:v2.0`).

| Mode | What the function does |
|---|---|
| `vlan` | Leaves NAD masters untouched (native Nephio VLAN values). |
| `nic` | Replaces each macvlan `master` with the physical NIC from `*-interface` setters. |

### Problem it solves (nic mode)

Nephio's built-in `apply-replacements` function:
- ❌ **Truncates NAD JSON** — delimiter-based replacement drops `mode`, `ipam`, `tuning` fields
- ❌ **Cannot select NADs by annotation** — v0.1.1 ignores `select.annotations`, so multi-interface NFs (UPF with N3/N4/N6) all get the same NIC

### How `nad-master-fn` works

1. Reads `networking-mode` and interface-to-NIC mappings from `interface-setters.yaml`
2. Finds each NAD by its `specializer.nephio.org/owner` annotation (no hardcoded names)
3. In `nic` mode: parses `spec.config` as proper JSON and replaces **only** the `master` field
4. In `vlan` mode: passes NADs through unchanged
5. Works for any cluster name (no hardcoding required)

### Usage in PackageVariant

```yaml
pipeline:
  mutators:
    - image: ghcr.io/kptdev/krm-functions-catalog/apply-setters:v0.2
      configMap:
        networking-mode: vlan   # or "nic"
        n3-interface: ens1f0    # used only in nic mode
        n4-interface: eno49
```

### Build & Push

```bash
cd nad-master-fn
docker build -t docker.io/org-container-repo/nad-master-fn:v2.0 .
docker push docker.io/org-container-repo/nad-master-fn:v2.0
```

**Image:** `docker.io/rehanfazal47/nad-master-fn:v2.0`

**Note:** Replace `org-container-repo` with your actual container registry organization/username.

---

## Prerequisites

### Management Cluster

| Component | Purpose |
|---|---|
| Porch | Package orchestration (kpt-as-a-service) |
| Config Sync | GitOps sync to workload clusters |
| IPAM Controller | Automatic IP address allocation |
| NAD Controller | Network Attachment Definition generation |

### Workload Clusters

| Cluster | Purpose | Provisioning |
|---|---|---|
| `ran` | OAI-RAN deployment | BYOH, kubeadm, or any CAPI provider |
| `core` | SD-Core deployment | BYOH, kubeadm, or any CAPI provider |

**Node requirements:**
- Kubernetes v1.28+ with kubeadm
- Physical NIC(s) for data plane traffic (e.g., `eno49`, `ens1f0`)
- `containerd` as container runtime
- Calico CNI (or any primary CNI)

### Git Repositories

| Repository | Type | Content |
|---|---|---|
| `nephio-workload-blueprints` | Upstream (Package) | All blueprint packages |
| `ran` | Downstream (Deployment) | Rendered packages for the RAN cluster |
| `core` | Downstream (Deployment) | Rendered packages for the Core cluster |

---

## Configuration — What to Customize

### 1. WorkloadCluster — Master Interface

In `networking-mode: vlan`, this is the **single trunk NIC** that all VLAN sub-interfaces hang off (Nephio native behavior). Must match `vlan-agent` `master-interface` setter.

```yaml
# clusterconfig/ran-workloadcluster.yaml
spec:
  masterInterface: ens4f0   # ← your node's trunk/data-plane NIC
```

For the full `vlan` vs `nic` guide (where to set `networking-mode`, deploy order, verification), see [Host Networking Modes](#host-networking-modes-vlan-vs-nic).

### 2. Repositories — Git URLs

Porch needs **this Nephfon repo as upstream** (`directory: /nfo-blueprints`) and **two separate downstream Git repos** (empty repos Porch writes rendered packages into). They are not the same clone.

Copy `repositories/repo-urls.env.example` to `repositories/repo-urls.env`, set the three URLs, and run `repositories/configure-repos.sh`. That updates `repositories/*.yaml` and `clusterconfig/rootsync-*.yaml`. See [`repositories/README.md`](repositories/README.md).

### Using Private Git Repositories

If your repositories are **private**, you need to create a Kubernetes Secret with Git credentials before registering them.

**Step 1: Create a GitHub Personal Access Token (PAT)**

Go to GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens. Create a token with `repo` scope (read/write access to your repositories).

**Step 2: Create the Secret on the management cluster**

```bash
kubectl create secret generic git-credentials \
  --namespace=default \
  --type=kubernetes.io/basic-auth \
  --from-literal=username=<your-github-username> \
  --from-literal=password=<your-github-PAT>
```

**Step 3: Add `secretRef` to each Repository CR**

```yaml
# Example: upstream-repos.yaml (private)
apiVersion: config.porch.kpt.dev/v1alpha1
kind: Repository
metadata:
  name: nephio-workload-blueprints
spec:
  type: git
  content: Package
  deployment: false
  git:
    repo: https://github.com/LFN-Super-Blueprints/nephfon.git
    branch: main
    directory: /nfo-blueprints
    secretRef:
      name: git-credentials    # ← references the Secret

# Same for downstream repos:
# ran-downstream-repo.yaml and core-downstream-repo.yaml
# Add secretRef under spec.git if those repos are also private
```

> **Tip:** If all repos belong to the same GitHub user/org, one Secret works for all. For different orgs, create separate Secrets (e.g., `git-creds-upstream`, `git-creds-downstream`).

### 3. PackageVariant NICs

Set the physical NIC for each 5G interface in the PackageVariant:

```yaml
# SD-Core UPF (sdcore/sdcore-pv.yaml)
configMap:
  n3-interface: eno49     # UPF ↔ gNB
  n4-interface: eno50     # UPF ↔ SMF
  n6-interface: ens1f0    # UPF → internet

# OAI-RAN CUCP (oai-ran/oai-ran-pv.yaml)
configMap:
  e1-interface: eno49     # CUCP ↔ CUUP
  f1c-interface: eno49    # CUCP ↔ DU
  n2-interface: eno49     # CUCP → AMF
```

---

## Deployment Guide

### Phase 0: Config Sync + RootSync

```bash
# Install Config Sync on each workload cluster
kubectl apply -f https://github.com/GoogleContainerTools/kpt-config-sync/releases/latest/download/config-sync-manifest.yaml \
  --kubeconfig ran.kubeconfig
kubectl apply -f https://github.com/GoogleContainerTools/kpt-config-sync/releases/latest/download/config-sync-manifest.yaml \
  --kubeconfig core.kubeconfig

# Create RootSync CRs
kubectl apply -f clusterconfig/rootsync-ran.yaml --kubeconfig ran.kubeconfig
kubectl apply -f clusterconfig/rootsync-core.yaml --kubeconfig core.kubeconfig
```

### Phase 1: Prerequisites (Management Cluster)

```bash
# Step 1a: RAN cluster config
kubectl apply -f clusterconfig/ran-clustercontext.yaml
kubectl apply -f clusterconfig/ran-workloadcluster.yaml

# Step 1b: Core cluster config
kubectl apply -f clusterconfig/core-clustercontext.yaml
kubectl apply -f clusterconfig/core-workloadcluster.yaml

# Step 2: Git repositories
kubectl apply -f repositories/upstream-repos.yaml
kubectl apply -f repositories/ran-downstream-repo.yaml
kubectl apply -f repositories/core-downstream-repo.yaml

# Step 3a: OAI-RAN prerequisites (self-contained — includes shared networks)
kubectl apply -f prerequisites/oai-ran/vlanindex-ran.yaml
kubectl apply -f prerequisites/oai-ran/networks-ran.yaml
kubectl apply -f prerequisites/oai-ran/ipprefixes-ran.yaml

# Step 3b: SD-Core prerequisites (self-contained — includes shared networks)
kubectl apply -f prerequisites/sd-core/vlanindex-core.yaml
kubectl apply -f prerequisites/sd-core/networks-core.yaml
kubectl apply -f prerequisites/sd-core/ipprefixes-core.yaml
```

### Phase 2: Cluster Foundation

```bash
# RAN cluster foundation
kubectl apply -f packagevariants/baseline/baseline-ran.yaml
kubectl apply -f packagevariants/addons/addons-ran.yaml

# Core cluster foundation
kubectl apply -f packagevariants/baseline/baseline-core.yaml
kubectl apply -f packagevariants/addons/addons-core.yaml
```

### Phase 3: Networking

```bash
# RAN cluster — Multus + vlan-agent (automates Nephio docs VLAN script)
kubectl apply -f packagevariants/networking/networking-ran.yaml
kubectl apply -f packagevariants/networking/vlan-agent-ran.yaml

# Core cluster
kubectl apply -f packagevariants/networking/networking-core.yaml
kubectl apply -f packagevariants/networking/vlan-agent-core.yaml
```

Wait for `vlan-agent` pods to be Running on every node before deploying NFs. The agent creates VLAN sub-interfaces (`<masterInterface>.<vlanID>`) that nad-fn writes into NADs.

### Phase 4: OAI-RAN (ran cluster)

```bash
kubectl apply -f packagevariants/oai-ran/oai-ran-pv.yaml
```

**Expected pods on ran cluster:**

```
NAMESPACE          NAME                                      READY   STATUS    
oai-cn-operators   oai-amf-operator-xxx                      1/1     Running   
oai-cn-operators   oai-ausf-operator-xxx                     1/1     Running   
oai-cn-operators   oai-nrf-operator-xxx                      1/1     Running   
oai-cn-operators   oai-smf-operator-xxx                      1/1     Running   
oai-cn-operators   oai-udm-operator-xxx                      1/1     Running   
oai-cn-operators   oai-udr-operator-xxx                      1/1     Running   
oai-ran-operators  oai-ran-operator-xxx                      1/1     Running   
oai-core           amf-ran-xxx                               0/1     Init:0/1  
oai-ran-cucp       oai-cu-cp-xxx                             1/1     Running   
oai-ran-cuup       oai-cu-up-xxx                             1/1     Running   
oai-ran-du         oai-du-xxx                                1/1     Running   
```

> **Note:** The `amf-ran` pod in `Init:0/1` state is expected. It is deployed only as a dependency for the OAI CUCP. This pod will remain in the Init phase and does not affect the RAN deployment.

### Phase 5: SD-Core (core cluster)

```bash
kubectl apply -f packagevariants/sdcore/sdcore-pv.yaml
```

**Expected pods on core cluster:**

```
NAMESPACE          NAME                                      READY   STATUS    
sdcore5g-cp        amf-core-xxx                              1/1     Running   
sdcore5g-cp        smf-core-xxx                              1/1     Running   
sdcore5g-cp        nrf-xxx                                   1/1     Running   
sdcore5g-cp        kafka-0                                   1/1     Running   
sdcore5g-cp        mongodb-0                                 1/1     Running   
sdcore5g-upf       upf-core-0                                5/5     Running   
sdcore5g           sdcore5g-operator-xxx                     2/2     Running   
```

---

## Porchctl CLI Installation

`porchctl` is the CLI tool for managing Porch package revisions. It is required for approving, rejecting, and managing package lifecycle.

**Install on Linux (amd64):**

```bash
# Download
curl -LO "https://github.com/nephio-project/porch/releases/download/v1.5.7/porchctl_1.5.7_linux_amd64.tar.gz"

# Extract and install
tar -xzf porchctl_1.5.7_linux_amd64.tar.gz
sudo install -o root -g root -m 0755 porchctl /usr/local/bin/

# Verify
porchctl version
```

**Install on Linux (arm64):**

```bash
curl -LO "https://github.com/nephio-project/porch/releases/download/v1.5.7/porchctl_1.5.7_linux_arm64.tar.gz"
tar -xzf porchctl_1.5.7_linux_arm64.tar.gz
sudo install -o root -g root -m 0755 porchctl /usr/local/bin/
```

**Non-root install (any platform):**

```bash
tar -xzf porchctl_1.5.7_linux_amd64.tar.gz
chmod +x ./porchctl
mkdir -p ~/.local/bin
mv ./porchctl ~/.local/bin/porchctl
# Add ~/.local/bin to $PATH in your shell profile
```

> For other platforms and versions, see the [official Porch documentation](https://docs.porch.nephio.org/docs/3_getting_started/installing-porchctl/).

---

## Troubleshooting

### Approving New Package Revisions

When an upstream blueprint repo is updated after the initial deployment, Porch creates a **new package revision** (e.g., `packagevariant-2`) in `Draft` state. The Nephio UI may stop showing the deployment until the new revision is approved and published.

**Step 1: List all package revisions to find the new one**

```bash
porchctl rpkg get -n default
```

Look for revisions with lifecycle `Draft` — these are the new revisions that need approval.

**Step 2: Propose the package revision**

```bash
kubectl patch packagerevisions <package-revision-name> -n default \
  --type='merge' -p '{"spec":{"lifecycle":"Proposed"}}'
```

**Step 3: Approve and publish the package revision**

```bash
porchctl rpkg approve <package-revision-name> -n default
```

> **Example:** If `multus-cni` has a new revision `multus-cni-ran-packagevariant-2` stuck in Draft:
> ```bash
> kubectl patch packagerevisions multus-cni-ran-packagevariant-2 -n default \
>   --type='merge' -p '{"spec":{"lifecycle":"Proposed"}}'
> porchctl rpkg approve multus-cni-ran-packagevariant-2 -n default
> ```

### "no available routes" IPAM Error

Missing `cluster-name` labels in Network prefixes. Verify:

```bash
kubectl get networks.infra.nephio.org <vpc-name> -o yaml | grep cluster-name
```

### Image Pull Errors

Known image fixes already applied in blueprints:

| Component | Fix |
|---|---|
| MongoDB, Kafka, Zookeeper | `docker.io/bitnami/` → `docker.io/bitnamilegacy/` |
| kube-rbac-proxy (operator) | `gcr.io/kubebuilder/` → `registry.k8s.io/kubebuilder/` |

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Custom KRM function (`nad-master-fn`) | Replaces broken `apply-replacements` — proper JSON parsing, annotation-based NAD selection |
| Separated prerequisites | Clean separation of OAI-RAN vs SD-Core network configs |
| Pre-baked Network CR labels | Eliminates manual `kubectl patch` after deployment |
| `bitnamilegacy` images | Old Bitnami images moved to legacy registry |
| Single upstream blueprint repo | All packages in one place — simpler management |
| Separate workload clusters | RAN and Core on different clusters — matches real-world 5G topology |

---

## Tested On

Reference deployment is running in the **UNH lab**.

- **Management cluster:** Ubuntu 22.04, Kubernetes v1.32, Nephio R5
- **Workload clusters:** Ubuntu 22.04, Kubernetes v1.32, kubeadm, BYOH provider
- **OAI-RAN:** v2.3.0 (CUCP, CUUP, DU)
- **SD-Core:** Aether SD-Core 5G
- **KRM function:** `docker.io/rehanfazal47/nad-master-fn:v2.0` — supports `vlan` (native Nephio) and `nic` (direct physical NIC) modes

---

## Contributors

Main contributor: Rehan Fazal, mdrehanfazal326@gmail.com (LF-ID: rehanfazal). Blueprint owner: Sridhar K. N. Rao, srao@linuxfoundation.org (LF-ID: sridharkn).

---

## License

Refer to the individual upstream projects for their respective licenses:

- [Nephio](https://github.com/nephio-project) — Apache 2.0
- [OpenAirInterface](https://gitlab.eurecom.fr/oai/openairinterface5g) — OAI Public License
- [Aether SD-Core](https://github.com/omec-project) — Apache 2.0
