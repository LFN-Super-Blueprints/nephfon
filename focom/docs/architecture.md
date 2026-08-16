# FOCOM architecture and spec mapping

SMO-facing FOCOM creates O2IMS-style `ProvisioningRequest` objects. The O2IMS operator prepares hosts (Ansible) and creates Cluster API BYOH resources.

```
SMO / lab operator
        |  FocomProvisioningRequest
        v
FOCOM operator  -->  O2IMS operator  -->  CAPI BYOH
                                              |
                         +--------------------+--------------------+
                         v                                         v
                   Workload: ran                             Workload: core
```

## Workflow

1. One-time: `./mgmt.sh` (management cluster, CAPI + BYOH, operators).
2. Configure hosts and clusters in `input.json`.
3. Apply `examples/focom-all-clusters.yaml` (recommended), or another method in [provisioning.md](provisioning.md).
4. FOCOM validates config and creates `ProvisioningRequest` CRs.
5. O2IMS runs Ansible (`site.yaml`) if hosts are not registered, then applies CAPI/BYOH objects.
6. Status: Cluster Provisioned → ProvisioningRequest `fulfilled` → FocomProvisioningRequest `Synced`.

Scale and delete are described in [provisioning.md](provisioning.md) and [operations.md](operations.md).

## Operators

| Component | Role | Input | Output |
|-----------|------|-------|--------|
| FOCOM | SMO-facing interface | `FocomProvisioningRequest` | `ProvisioningRequest` |
| O2IMS-style operator | Cluster LCM | `ProvisioningRequest` | BYOH CAPI resources |
| BYOH controller | Bare-metal provisioner | CAPI resources | Kubernetes on hosts |

FOCOM supports `allClusters`, `clusterNames`, and inline `templateParameters`. This implementation uses Kubernetes CRs and a hostPath-mounted `input.json`. It is **not** the Nephio Porch Git-backed FOCOM NBI.

## CRDs

**FocomProvisioningRequest:** `allClusters`, `clusterNames`, `templateParameters`, `operation` (create / scale / delete).

**ProvisioningRequest:** `templateParameters.clusterName`, host assignments, `status.provisioningState` (`pending` / `progressing` / `fulfilled` / `failed`).

## O-RAN and CAPI mapping

| Source | Used for |
|--------|----------|
| O-RAN.WG6.TS.O2IMS-INTERFACE §3.4 | ProvisioningRequest shape, status, templateParameters |
| O-RAN.WG6.TR.FOCOM-NFO-SMOS-NBI UC 4.2.3 | FocomProvisioningRequest; batch fields are an extension |
| CAPI `cluster.x-k8s.io/v1beta1` | Cluster, MachineDeployment, KubeadmControlPlane |
| BYOH `infrastructure.cluster.x-k8s.io/v1beta1` | ByoCluster, ByoHost, ByoMachineTemplate |

`templateParameters` (clusterName, k8sVersion, hosts) come from `input.json` or from the CR.

Links: [O-RAN specifications](https://www.o-ran.org/specifications), [Cluster API](https://cluster-api.sigs.k8s.io/), [BYOH](https://github.com/vmware-tanzu/cluster-api-provider-bringyourownhost), [Nephio](https://nephio.org/).
