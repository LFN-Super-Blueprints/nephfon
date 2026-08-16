# nad-master-fn

A custom KRM function that controls how the `master` field in
NetworkAttachmentDefinition (NAD) `spec.config` JSON is set, supporting
two user-selectable networking modes.

For the full user guide (deploy order, which PackageVariant files to edit,
verification commands), see the parent repo README section
**Host Networking Modes (`vlan` vs `nic`)**.

## Networking Modes

| Mode | Behavior | Host requirement |
|---|---|---|
| `vlan` | Leaves the NADs **untouched** — Nephio's native flow: `Interface (attachmentType: vlan)` → `VLANClaim` (vlan-specializer) → nad-fn renders `master: <masterInterface>.<vlanID>` (e.g. `ens4f0.6`) | VLAN sub-interfaces created by `vlan-agent` (`nephio-blueprints/networking/vlan-agent`) |
| `nic` | Replaces the macvlan `master` with a **physical NIC** per interface (e.g. `ens1f0`), bypassing Nephio's VLAN layer | Physical NICs must exist on the node |

The mode is read from the `networking-mode` key in the functionConfig.

- Blueprint / PackageVariant default today: **`vlan`** (set in `interface-setters.yaml`).
- If the key is **missing** entirely, the function falls back to **`nic`** (backward compatible with v1.0 configs).
- Any other value fails the render with an error.

```
mode: vlan                         mode: nic
─────────                          ────────
NAD master stays                   NAD master overwritten
  ens4f0.6                           eno49
vlan-agent creates ens4f0.6        no VLAN needed
```

## What It Does (nic mode)

1. Reads interface-to-NIC mappings from `functionConfig` (ConfigMap)
2. Finds all NAD resources by `specializer.nephio.org/owner` annotation
3. Parses `spec.config` as proper JSON
4. Replaces **only** the `master` field in the macvlan plugin
5. Preserves all other JSON fields (`mode`, `ipam`, `tuning`, etc.)

## Why It Exists

- Nephio's built-in `apply-replacements` function uses a delimiter-based
  approach that **truncates NAD JSON** when replacing the master field.
  This function parses the JSON properly and modifies only the master field.
- Nephio's nad-fn only supports a single cluster-wide `masterInterface`;
  `nic` mode enables a **different physical NIC per 3GPP interface**.
- `vlan` mode restores Nephio's native VLAN networking as one of the
  selectable host networking options.

## Usage

### In Kptfile (blueprint pipeline):
```yaml
pipeline:
  mutators:
    - image: docker.io/rehanfazal47/nad-master-fn:v2.0
      configPath: interface-setters.yaml
```

### In PackageVariant (admin selects mode and NICs):
```yaml
pipeline:
  mutators:
    - image: ghcr.io/kptdev/krm-functions-catalog/apply-setters:v0.2
      configMap:
        networking-mode: nic   # or "vlan"
        n3-interface: ens1f0
        n4-interface: eno49
        n6-interface: eno50
```

### ConfigMap format (interface-setters.yaml):
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: interface-setters
  annotations:
    config.kubernetes.io/local-config: "true"
data:
  networking-mode: "nic"    # kpt-set: ${networking-mode}
  n3-interface: "ens1f0"    # kpt-set: ${n3-interface}
  n4-interface: "eno49"     # kpt-set: ${n4-interface}
  n6-interface: "eno50"     # kpt-set: ${n6-interface}
```

In `vlan` mode the `*-interface` keys are ignored; the NAD master is
whatever nad-fn generated from `WorkloadCluster.spec.masterInterface`
plus the allocated VLAN ID.

## Build

```bash
# Build binary
go build -o nad-master-fn .

# Build Docker image
docker build -t docker.io/rehanfazal47/nad-master-fn:v2.0 .

# Push to Docker Hub
docker push docker.io/rehanfazal47/nad-master-fn:v2.0
```

## Interface Mapping Convention (nic mode)

The function maps annotation owners to NIC config keys:

| NAD Annotation | Config Key | Example NIC |
|---|---|---|
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n2` | `n2-interface` | `ens4f1` |
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n3` | `n3-interface` | `ens1f0` |
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n4` | `n4-interface` | `eno49` |
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n6` | `n6-interface` | `eno50` |
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.e1` | `e1-interface` | `eno49` |
| `specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.f1c` | `f1c-interface` | `ens1f0` |
