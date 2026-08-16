# Nephfon

**Nephio-based FOCOM and NFO** — a combined LFN 5G Super Blueprint candidate.

Blueprint owner: **Sridhar K. N. Rao** <srao@linuxfoundation.org> (LF-ID: **sridharkn**).

This repository merges three student implementations into one tree:

| Folder | Original repo | Role |
|--------|----------------|------|
| [`focom/`](focom/) | `byoh-nephio` | FOCOM + O2IMS-style cluster LCM; provisions BYOH (CAPI) workload clusters |
| [`nfo-blueprints/`](nfo-blueprints/) | `nephio-blueprints` | kpt packages for OAI RAN and Aether SD-Core |
| [`nfo-management/`](nfo-management/) | `nephio-management-config` | Nephio Porch PackageVariants, cluster context, and GitOps wiring |

Intended GitHub home: **LFN 5G SBP** org (`lfn` / 5gsbp). After the first push, update Git URLs in `nfo-management/repositories/*.yaml`.

## What this stack does

1. **FOCOM path (`focom/`)** — SMO-facing `FocomProvisioningRequest` creates O2IMS-style `ProvisioningRequest` objects. An O2IMS operator prepares hosts with Ansible and creates Cluster API BYOH resources. Result: `ran` and `core` Kubernetes clusters on Linux servers.
2. **NFO path (`nfo-management/` + `nfo-blueprints/`)** — After Nephio is installed on the management cluster, Porch clones kpt blueprints and Config Sync deploys **OAI RAN** (CU-CP, CU-UP, DU) on the RAN cluster and **Aether SD-Core** (AMF, SMF, UPF, NRF, and related CP functions) on the core cluster.

End-to-end order: FOCOM clusters first, then Nephio install on the management cluster, then NFO PackageVariants.

## Documentation

| Document | Location |
|----------|----------|
| FOCOM bring-up | [`focom/README.md`](focom/README.md) |
| FOCOM architecture and spec mapping | [`focom/docs/architecture.md`](focom/docs/architecture.md) |
| FOCOM provisioning (`input.json`, scale, direct O2IMS) | [`focom/docs/provisioning.md`](focom/docs/provisioning.md) |
| FOCOM tests and recovery | [`focom/docs/operations.md`](focom/docs/operations.md) |
| NFO deploy guide (OAI + SD-Core) | [`nfo-management/README.md`](nfo-management/README.md) |
| kpt packages | [`nfo-blueprints/README.md`](nfo-blueprints/README.md) |
| 5G SBP field set | [`docs/5G-SBP-BLUEPRINT.md`](docs/5G-SBP-BLUEPRINT.md) |

O-RAN references cited by the student work:

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

Documented test environment in `nfo-management/README.md`: Ubuntu 22.04, Kubernetes v1.32, Nephio R5, OAI-RAN v2.3.0, Aether SD-Core.

## Claim check (code review, not a live lab)

**Supported by code and manifests**

- FOCOM and O2IMS Python operators, CRDs, Ansible host prep, BYOH CAPI generation (`focom/`).
- Batch cluster create from `input.json` and `examples/focom-all-clusters.yaml`.
- Distinct `cluster_type` `ran` vs `core` host prerequisites in Ansible.
- Nephio PackageVariants that target `ran` for OAI and `core` for SD-Core.
- kpt packages for OAI CU-CP/CU-UP/DU and SD-Core CP, operator, UPF, AMF, SMF.
- Custom `nad-master-fn` for VLAN vs physical-NIC NAD `master` fields.

**Partially true / caveats**

- FOCOM here is a **Kubernetes operator + hostPath `input.json`**, not the Nephio Porch Git-backed FOCOM NBI described in [nephio#1066](https://github.com/nephio-project/nephio/issues/1066). It is O-RAN-inspired, not a full WG6/Nephio FOCOM NBI.
- O2IMS is an **O2IMS-style ProvisioningRequest CRD**, not a certified O-Cloud IMS product.
- NFO is **Nephio PackageVariant deployment of OAI and SD-Core**, not a separate NFO microservice with O-RAN NFO APIs.
- README “tested” tables are student-reported; this consolidation did not re-run the lab.
- `nfo-blueprints/workloads/oai-ran/.../README.md` still describes older catalog/package-variant paths; the working path is `nfo-management/`.
- Container image `docker.io/rehanfazal47/nad-master-fn:v2.0` is personal; republish under the 5G SBP org before a public demo.
- Git repo URLs still point at `rehanfazal77/...`; update after the LFN push.
- No demo video found in these trees.

## Realization (short)

1. Prepare Linux servers and fill `focom/input.json`.
2. Run `focom/mgmt.sh` (management cluster, CAPI BYOH, operators).
3. `kubectl apply -f focom/examples/focom-all-clusters.yaml`.
4. Install Nephio on the management cluster (see `focom/README.md`).
5. Point `nfo-management/repositories/*.yaml` at this repo (`directory: /nfo-blueprints` for upstream).
6. Apply clusterconfig, prerequisites, then PackageVariants per `nfo-management/README.md`.

## License

Apache License 2.0 for this integration and operators. OAI components remain under the OAI Public License; see upstream projects.
