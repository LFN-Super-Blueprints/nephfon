# Nephfon

**Nephio-based FOCOM and NFO** — an LFN 5G Super Blueprint.

**Owner:** Sridhar K. N. Rao, srao@linuxfoundation.org (LF-ID: **sridharkn**)

**Main contributor:** Rehan Fazal, mdrehanfazal326@gmail.com (LF-ID: **rehanfazal**)

This repository combines FOCOM cluster lifecycle management and NFO network-function deployment:

| Folder | Role |
|--------|------|
| [`focom/`](focom/) | FOCOM + O2IMS-style cluster LCM; provisions BYOH (CAPI) workload clusters |
| [`nfo-blueprints/`](nfo-blueprints/) | kpt packages for OAI RAN and Aether SD-Core |
| [`nfo-management/`](nfo-management/) | Nephio Porch PackageVariants, cluster context, and GitOps wiring |

Published at [LFN-Super-Blueprints/nephfon](https://github.com/LFN-Super-Blueprints/nephfon).

A reference deployment is **up and running in the UNH lab** and can be used to walk through the same FOCOM and NFO flows.

## What this stack does

1. **FOCOM (`focom/`)** — SMO-facing `FocomProvisioningRequest` creates O2IMS-style `ProvisioningRequest` objects. An O2IMS operator prepares hosts with Ansible and creates Cluster API BYOH resources. Result: `ran` and `core` Kubernetes clusters on Linux servers.
2. **NFO (`nfo-management/` + `nfo-blueprints/`)** — After Nephio is installed on the management cluster, Porch clones kpt blueprints and Config Sync deploys **OAI RAN** (CU-CP, CU-UP, DU) on the RAN cluster and **Aether SD-Core** (AMF, SMF, UPF, NRF, and related CP functions) on the core cluster.

End-to-end order: FOCOM clusters first, then Nephio on the management cluster, then NFO PackageVariants.

## Documentation

| Document | Location |
|----------|----------|
| FOCOM bring-up | [`focom/README.md`](focom/README.md) |
| FOCOM architecture and spec mapping | [`focom/docs/architecture.md`](focom/docs/architecture.md) |
| FOCOM provisioning (`input.json`, scale, direct O2IMS) | [`focom/docs/provisioning.md`](focom/docs/provisioning.md) |
| FOCOM tests and recovery | [`focom/docs/operations.md`](focom/docs/operations.md) |
| NFO deploy guide (OAI + SD-Core) | [`nfo-management/README.md`](nfo-management/README.md) |
| kpt packages | [`nfo-blueprints/README.md`](nfo-blueprints/README.md) |
| Git URL configuration | [`nfo-management/repositories/`](nfo-management/repositories/) |
| 5G SBP field set | [`docs/5G-SBP-BLUEPRINT.md`](docs/5G-SBP-BLUEPRINT.md) |

O-RAN references:

- O-RAN.WG6.TS.O2IMS-INTERFACE (ProvisioningRequest)
- O-RAN.WG6.TR.FOCOM-NFO-SMOS-NBI (FOCOM NBI / NFO)

Nephio O-RAN integration overview: [nephio-project/docs o-ran-integration](https://github.com/nephio-project/docs/blob/main/content/en/docs/network-architecture/o-ran-integration.md).

## High-level architecture

```
                         SMO / 5G SBP operator
                                  |
                    FocomProvisioningRequest
                                  v
+------------------------------------------------------------------+
| Management cluster                                               |
|  FOCOM operator  -->  O2IMS operator  -->  CAPI BYOH             |
|  Nephio: Porch, IPAM, NAD, Config Sync                           |
+-----------------------------+------------------------------------+
                              |
              +---------------+----------------+
              v                                v
        Workload: ran                    Workload: core
        OAI CU-CP / CU-UP / DU           SD-Core AMF / SMF / UPF / CP
```

## Lab topology (typical)

```
[Mgmt node]  Ubuntu, K8s + Nephio + FOCOM/O2IMS/BYOH
     |
     +-- SSH --> [RAN hosts]  hugepages; OAI RAN NFs; Multus + vlan-agent
     +-- SSH --> [Core hosts] inotify/sandbox tweaks; SD-Core NFs
```

Reference environment (UNH lab and `nfo-management/README.md`): Ubuntu 22.04, Kubernetes v1.32, Nephio R5, OAI-RAN v2.3.0, Aether SD-Core.

## Current status

Working in the UNH lab today:

- FOCOM and O2IMS operators, CRDs, Ansible host prep, and BYOH CAPI cluster create (`focom/`).
- Batch cluster create from `input.json` and `examples/focom-all-clusters.yaml`.
- Distinct `cluster_type` `ran` vs `core` host prerequisites in Ansible.
- Nephio PackageVariants that deploy OAI on `ran` and SD-Core on `core`.
- kpt packages for OAI CU-CP/CU-UP/DU and SD-Core CP, operator, UPF, AMF, SMF.
- `nad-master-fn` for VLAN vs physical-NIC NAD `master` fields.

### Caveats

- FOCOM is implemented as Kubernetes operators (`FocomProvisioningRequest` → `ProvisioningRequest` → CAPI BYOH), aligned with O-RAN WG6 FOCOM/O2IMS concepts. A Git/Porch REST FOCOM NBI has been discussed in Nephio as a **proposal** (not an approved specification); this blueprint does not depend on it.
- Cluster LCM uses an O2IMS-**style** `ProvisioningRequest` CRD suitable for this lab topology.
- NFO is implemented with Nephio PackageVariants (the usual Nephio path). A separate NFO NBI microservice is not required for this blueprint.

### TODO

- Publish a public demo video of the UNH lab (FOCOM apply → clusters Ready → OAI/SD-Core pods).
- Optionally republish `nad-master-fn` under an LFN-owned registry; the function source is in `nfo-management/nad-master-fn/` and the image in use is `docker.io/rehanfazal47/nad-master-fn:v2.0`.

## Realization (short)

1. Prepare Linux servers and fill `focom/input.json`.
2. Run `focom/mgmt.sh` (management cluster, CAPI BYOH, operators).
3. `kubectl apply -f focom/examples/focom-all-clusters.yaml`.
4. Install Nephio on the management cluster (see `focom/README.md`).
5. Set Git URLs (this repo as Porch **upstream**; separate **downstream** repos for `ran` and `core`) — see `nfo-management/repositories/repo-urls.env.example`.
6. Apply clusterconfig, prerequisites, then PackageVariants per `nfo-management/README.md`.

## License

Apache License 2.0 for this integration and operators. OAI components remain under the OAI Public License; see upstream projects.
