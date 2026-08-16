# Nephio Workload Blueprints

Upstream kpt packages for deploying 5G network functions on Kubernetes clusters managed by [Nephio](https://nephio.org). Contains all blueprint packages for OAI-RAN and Aether SD-Core deployments.

## What Are Blueprints?

In Nephio, a **blueprint** is a kpt package that defines a Kubernetes workload as a set of YAML manifests. Blueprints are stored in an upstream Git repository and rendered by [Porch](https://kpt.dev/guides/porch-user-guide) into cluster-specific configurations via **PackageVariants**.

```
Blueprint (this repo)          PackageVariant (mgmt cluster)        Workload Cluster
┌──────────────────┐          ┌─────────────────────┐            ┌──────────────────┐
│ Generic YAML     │── Porch ─│ Injects cluster-    │── Porch ───│ Rendered YAML    │
│ with kpt setters │  renders │ specific values     │  publishes │ with real values │
│ (defaults)       │          │ (IPs, NICs, names)  │            │ (deployed via    │
│                  │          │                     │            │  Config Sync)    │
└──────────────────┘          └─────────────────────┘            └──────────────────┘
```

## Repository Structure

```
nephio-workload-blueprints/
│
├── cluster-baseline/                      CLUSTER FOUNDATION
│   ├── Kptfile
│   ├── namespaces.yaml                    Workload namespaces
│   ├── storage-class.yaml                 Local-path StorageClass
│   └── pod-security.yaml                  Pod security policies
│
├── platform-addons/                       PLATFORM ADDONS
│   ├── Kptfile
│   ├── monitoring/metrics-server.yaml     Kubernetes Metrics Server
│   ├── storage/local-path-provisioner.yaml
│   └── resource-management/resource-quotas.yaml
│
├── networking/                            NETWORKING
│   ├── multus-cni/                        Multus CNI + macvlan support
│   │   ├── Kptfile
│   │   ├── multus-daemonset.yaml
│   │   ├── cni-plugins-installer.yaml
│   │   └── *-crd.yaml                     NAD, Network, NFDeployment CRDs
│   └── vlan-agent/                        Automated VLAN sub-interface creation
│       ├── Kptfile
│       ├── daemonset.yaml                 Watches NADs, creates <nic>.<vlanID>
│       ├── configmap.yaml                 Reconcile script + optional static range
│       └── rbac.yaml
│
└── workloads/
    │
    ├── oai-ran/                           OAI 5G RAN
    │   └── oai-ran/
    │       ├── oai-cp-operators/          OAI Core CP Operators (CRDs only)
    │       ├── oai-ran-operator/          OAI RAN Operator
    │       ├── pkg-example-cucp-bp/       CU Control Plane (E1, F1-C, N2)
    │       │   ├── Kptfile                Pipeline: ... → nad-fn → nad-master-fn
    │       │   └── interface-setters.yaml NIC mapping (kpt-set variables)
    │       ├── pkg-example-cuup-bp/       CU User Plane (E1, F1-U, N3)
    │       │   ├── Kptfile
    │       │   └── interface-setters.yaml
    │       ├── pkg-example-du-bp/         Distributed Unit (F1)
    │       │   ├── Kptfile
    │       │   └── interface-setters.yaml
    │       └── pkg-example-ue-bp*/        UE Simulators
    │
    └── sd-core/                           AETHER SD-CORE 5G
        ├── sdcore5g-cp/                   Control Plane (NRF, UDR, UDM, AUSF,
        │   ├── Kptfile                    PCF, NSSF, WebUI, MongoDB, Kafka)
        │   ├── kafka/                     bitnamilegacy images
        │   └── mongodb/                   bitnamilegacy images
        │
        ├── sdcore5g-operator/             SD-Core Operator
        │   └── operator/deployment.yaml   registry.k8s.io kube-rbac-proxy
        │
        ├── pkg-example-upf-bp/            User Plane Function (N3, N4, N6)
        │   ├── Kptfile                    Pipeline: ... → nad-fn → nad-master-fn
        │   └── interface-setters.yaml     NIC mapping (kpt-set variables)
        │
        ├── pkg-example-amf-bp/            AMF (N2)
        │   ├── Kptfile
        │   └── interface-setters.yaml
        │
        └── pkg-example-smf-bp/            SMF (N4)
            ├── Kptfile
            └── interface-setters.yaml
```

---

## Custom KRM Function: `nad-master-fn`

All NF blueprints with secondary network interfaces use a custom KRM function (`docker.io/rehanfazal47/nad-master-fn:v2.0`) as the **last step** in the Kptfile pipeline. It supports two user-selectable networking modes via the `networking-mode` key in `interface-setters.yaml`.

### Networking modes

| Mode | Behavior |
|---|---|
| `vlan` (default) | Leaves NADs **untouched** — Nephio's native flow: `Interface (attachmentType: vlan)` → `VLANClaim` (vlan-specializer) → nad-fn renders `master: <masterInterface>.<vlanID>`. The `vlan-agent` DaemonSet creates those VLAN sub-interfaces on nodes automatically. |
| `nic` | Replaces the macvlan `master` with a **physical NIC** per interface (e.g. `ens1f0`), bypassing the VLAN layer. |

### Why it's needed

Nephio's built-in `apply-replacements:v0.1.1` has two critical bugs when modifying NAD `spec.config`:

| Bug | Impact |
|---|---|
| **JSON truncation** | Delimiter-based replacement drops `mode`, `ipam`, `tuning` fields |
| **Selector limitation** | `select.annotations` is ignored — multi-interface NFs get the same NIC for all interfaces |

### How it works

```
Pipeline order:
  1. apply-setters (PV)  → writes NIC names to interface-setters.yaml
  2. ... Kptfile steps ... → interface-fn, dnn-fn, nad-fn generate NADs
  3. nad-master-fn        → reads interface-setters.yaml, fixes master per NAD

NAD identification: reads specializer.nephio.org/owner annotation
  "req.nephio.org/v1alpha1.Interface.n3" → extracts "n3" → looks up "n3-interface"
```

### Kptfile entry (all NF blueprints)

```yaml
pipeline:
  mutators:
    - ...                                            # existing steps
    - image: docker.io/rehanfazal47/nad-master-fn:v2.0
      configPath: interface-setters.yaml             # reads mode + NIC mapping
```

### Admin selects mode in PackageVariant

```yaml
pipeline:
  mutators:
    - image: ghcr.io/kptdev/krm-functions-catalog/apply-setters:v0.2
      configMap:
        networking-mode: vlan   # or "nic"
        n3-interface: ens1f0    # used only in nic mode
        n4-interface: eno49
```

---

## networking/vlan-agent

Automates the manual per-node VLAN setup that the [Nephio docs](https://docs.nephio.org/docs/guides/user-guides/usecase-user-guides/exercise-1-free5gc/) still require (`test-infra/e2e/provision/hacks/vlan-interfaces.sh`). The docs script creates `eth1.2` … `eth1.6` on each worker; this DaemonSet does the equivalent on every node and also reconciles VLAN sub-interfaces discovered from NAD `master` fields (`<masterInterface>.<vlanID>`).

Deploy together with `multus-cni`, **before** any NF workloads, when using `networking-mode: vlan`.

Source code is in the companion repo: [nephio-deployment-mgmt/nad-master-fn/](../nephio-deployment-mgmt/nad-master-fn/).

---

## Package Details

### cluster-baseline

Foundational package applied to every workload cluster. Sets up namespaces, storage classes, and pod security policies.

---

### platform-addons

Deploys monitoring and storage components: Metrics Server, Local Path Provisioner, Resource Quotas.

---

### networking/multus-cni

Deploys [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni) and CRDs for multi-network pod attachments. Required for all NFs with secondary interfaces.

---

---

### workloads/oai-ran

OAI 5G RAN packages — gNB split into CU-CP, CU-UP, and DU.

| Package | Interfaces | NIC Setters |
|---|---|---|
| `pkg-example-cucp-bp` | E1, F1-C, N2 | `e1-interface`, `f1c-interface`, `n2-interface` |
| `pkg-example-cuup-bp` | E1, F1-U, N3 | `e1-interface`, `f1u-interface`, `n3-interface` |
| `pkg-example-du-bp` | F1 | `f1-interface` |

---

### workloads/sd-core

Aether SD-Core 5G core network.

| Package | Interfaces | NIC Setters |
|---|---|---|
| `pkg-example-upf-bp` | N3, N4, N6 | `n3-interface`, `n4-interface`, `n6-interface` |
| `pkg-example-amf-bp` | N2 | `n2-interface` |
| `pkg-example-smf-bp` | N4 | `n4-interface` |

---

## Image Fixes Applied

| Component | Original (broken) | Fixed |
|---|---|---|
| MongoDB | `docker.io/bitnami/mongodb:6.0.4-debian-11-r0` | `docker.io/bitnamilegacy/mongodb:6.0.4-debian-11-r0` |
| Kafka | `docker.io/bitnami/kafka:3.3.1-debian-11-r34` | `docker.io/bitnamilegacy/kafka:3.3.1-debian-11-r34` |
| Zookeeper | `docker.io/bitnami/zookeeper:3.8.0-debian-11-r74` | `docker.io/bitnamilegacy/zookeeper:3.8.0-debian-11-r74` |
| kube-rbac-proxy | `gcr.io/kubebuilder/kube-rbac-proxy:v0.8.0` | `registry.k8s.io/kubebuilder/kube-rbac-proxy:v0.8.0` |

---

## kpt Function Images

| Function | Image | Used For |
|---|---|---|
| `apply-setters` | `ghcr.io/kptdev/krm-functions-catalog/apply-setters:v0.2` | Injecting PV values |
| `apply-replacements` | `ghcr.io/kptdev/krm-functions-catalog/apply-replacements:v0.1.1` | Owner/namespace replacement |
| `set-namespace` | `ghcr.io/kptdev/krm-functions-catalog/set-namespace:v0.4.1` | Setting resource namespaces |
| `nad-master-fn` | `docker.io/rehanfazal47/nad-master-fn:v2.0` | **NAD master mode control** (vlan or nic) |

> `apply-replacements` is still used for owner and namespace replacements. Only the NAD master replacement uses `nad-master-fn`.

---

## License

- [Nephio](https://github.com/nephio-project) — Apache 2.0
- [OpenAirInterface](https://gitlab.eurecom.fr/oai/openairinterface5g) — OAI Public License
- [Aether SD-Core](https://github.com/omec-project) — Apache 2.0
- [Multus CNI](https://github.com/k8snetworkplumbingwg/multus-cni) — Apache 2.0
