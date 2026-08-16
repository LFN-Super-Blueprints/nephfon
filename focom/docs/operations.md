# Testing and troubleshooting


Complete testing guide for the BYOH-O2IMS-FOCOM project.

## Prerequisites

Before running tests, ensure:

```bash
# 1. Management cluster running (after ./mgmt.sh)
kubectl get nodes

# 2. CAPI + BYOH installed
kubectl get pods -A | grep -E "capi|byoh"

# 3. Operators deployed
kubectl get pods -n o2ims-system
kubectl get pods -n focom-system

# 4. CRDs installed
kubectl get crd | grep -E "provisioning|focom"

# 5. Hosts defined in input.json
cat input.json
```

---

## Quick Validation Script

Run this script to quickly validate your setup:

```bash
#!/bin/bash
echo "=== BYOH-O2IMS-FOCOM Test Suite ==="

echo -e "\n[1/5] Checking Operators..."
kubectl get pods -n o2ims-system -o name 2>/dev/null | grep -q pod && echo "✅ O2IMS: Running" || echo "❌ O2IMS: Not running"
kubectl get pods -n focom-system -o name 2>/dev/null | grep -q pod && echo "✅ FOCOM: Running" || echo "❌ FOCOM: Not running"

echo -e "\n[2/5] Checking CRDs..."
kubectl get crd provisioningrequests.o2ims.provisioning.oran.org &>/dev/null && echo "✅ O2IMS CRD" || echo "❌ O2IMS CRD"
kubectl get crd focomprovisioningrequests.focom.nephio.org &>/dev/null && echo "✅ FOCOM CRD" || echo "❌ FOCOM CRD"

echo -e "\n[3/5] ByoHosts..."
HOSTS=$(kubectl get byohosts --no-headers 2>/dev/null | wc -l)
echo "📦 Registered: $HOSTS"

echo -e "\n[4/5] FocomProvisioningRequests..."
kubectl get fpr 2>/dev/null || echo "(none)"

echo -e "\n[5/5] Clusters..."
kubectl get clusters 2>/dev/null || echo "(none)"

echo -e "\n=== Done ==="
```

---

## Test Cases

### Test 1: Verify Operator Deployment

```bash
# Check O2IMS operator
kubectl get pods -n o2ims-system
# Expected: o2ims-controller-xxx  Running

# Check FOCOM operator
kubectl get pods -n focom-system
# Expected: focom-controller-xxx  Running

# Verify CRDs installed
kubectl get crd | grep -E "provisioning|focom"
```

✅ **Pass if:** Both operators running, CRDs exist

---

### Test 2: Batch Provisioning - All Clusters

```bash
# Provision ALL clusters from input.json
kubectl apply -f examples/focom-all-clusters.yaml

# Watch FPR status
kubectl get fpr -w
# Expected: Phase → Loading → Validating → Creating → Synced

# Check ProvisioningRequests created
kubectl get provisioningrequests
# Expected: One per cluster in input.json

# Watch clusters
kubectl get clusters -w
kubectl get machines -w
```

✅ **Pass if:** FPR shows `Synced`, all clusters show `Provisioned`

---

### Test 3: Batch Provisioning - Selected Clusters

Create a file `my-selected-clusters.yaml` (see [provisioning.md](provisioning.md#method-1-selected-clusters)):

```yaml
apiVersion: focom.nephio.org/v1alpha1
kind: FocomProvisioningRequest
metadata:
  name: create-selected-clusters
  namespace: default
spec:
  clusterNames:
    - "ran"
```

```bash
kubectl apply -f my-selected-clusters.yaml
kubectl get provisioningrequests
kubectl get fpr -w
```

✅ **Pass if:** Only selected clusters created

---

### Test 4: Template-Based Provisioning

Create a file `my-cluster-request.yaml` (see [provisioning.md](provisioning.md#method-2-template-based-focom)):

```bash
# Clean up previous (if needed)
kubectl delete fpr --all

# Apply template-based request
kubectl apply -f my-cluster-request.yaml

# Watch
kubectl get fpr -w
kubectl get provisioningrequests
kubectl get clusters
```

✅ **Pass if:** Cluster created with specified parameters

---

### Test 5: Direct O2IMS Provisioning (Skip FOCOM)

Create a file `direct-cluster.yaml` (see [provisioning.md](provisioning.md#method-3-direct-o2ims-request)):

```bash
# Apply directly to O2IMS operator
kubectl apply -f direct-cluster.yaml

# Watch
kubectl get provisioningrequests -w
kubectl get clusters
```

✅ **Pass if:** Cluster created without FPR

---

### Test 6: Validation - Even Number of Masters (Should Fail)

```bash
cat <<EOF | kubectl apply -f -
apiVersion: focom.nephio.org/v1alpha1
kind: FocomProvisioningRequest
metadata:
  name: test-even-masters
spec:
  templateName: "byoh-workload-cluster"
  templateParameters:
    clusterName: test
    hosts:
      masters:
        - hostName: m1
          hostIp: "10.0.0.1"
        - hostName: m2
          hostIp: "10.0.0.2"
      workers: []
EOF

# Check status
kubectl get fpr test-even-masters -o jsonpath='{.status.message}'
# Expected: Contains "odd"

# Cleanup
kubectl delete fpr test-even-masters
```

✅ **Pass if:** Status = Failed with "odd" in message

---

### Test 7: Workload Cluster Access

```bash
# Get cluster name
CLUSTER=$(kubectl get clusters -o jsonpath='{.items[0].metadata.name}')

# Get kubeconfig
kubectl get secret ${CLUSTER}-kubeconfig -o jsonpath='{.data.value}' | base64 -d > workload.kubeconfig

# Test workload cluster
kubectl --kubeconfig=workload.kubeconfig get nodes
kubectl --kubeconfig=workload.kubeconfig get pods -A
```

✅ **Pass if:** Nodes show Ready, system pods Running

---

### Test 8: Scaling Workers

Create a file `scale-cluster.yaml` (see [provisioning.md](provisioning.md#method-4-scale-cluster-workers)):

```bash
# Ensure new hosts are registered first
kubectl get byohosts

# Apply scale request
kubectl apply -f scale-cluster.yaml

# Watch
kubectl get fpr -w
kubectl get machines -w
```

✅ **Pass if:** Worker count increases, machines Ready

---

### Test 9: Delete Flow (Cleanup)

```bash
# Delete via FOCOM
kubectl delete fpr <name>

# Verify cascading delete
kubectl get provisioningrequests  # Should be deleted
kubectl get clusters              # Should be deleting

# ByoHosts remain for reuse
kubectl get byohosts
```

✅ **Pass if:** Resources deleted, ByoHosts remain

---

## Test Summary

| # | Test | Config Source | Expected Result |
|---|------|---------------|------------------|
| 1 | Operator Health | - | Both Running |
| 2 | Batch All | `focom-all-clusters.yaml` | All clusters created |
| 3 | Batch Selected | Inline YAML (see provisioning.md) | Only specified clusters |
| 4 | Template-based | Inline YAML (see provisioning.md) | Custom cluster config |
| 5 | Direct O2IMS | Inline YAML (see provisioning.md) | Skip FOCOM layer |
| 6 | Even Masters | - | Failed validation |
| 7 | Cluster Access | - | Nodes Ready |
| 8 | Scaling | Inline YAML (see provisioning.md) | Workers increase |
| 9 | Delete | - | Cascade delete |

---

## Expected End State

| Component | Expected Status |
|-----------|-----------------|
| O2IMS Operator | Running |
| FOCOM Operator | Running |
| ByoHosts | Registered |
| FocomProvisioningRequest | Synced |
| ProvisioningRequest | fulfilled |
| Cluster | Provisioned |

---

## Troubleshooting

### Operator Not Running

```bash
# Check logs
kubectl logs -n o2ims-system -l app=o2ims-controller
kubectl logs -n focom-system -l app=focom-controller
```

### Host Registration Failed

```bash
# Check Ansible jobs
kubectl get jobs -n o2ims-system
kubectl logs job/<job-name> -n o2ims-system
```

### Cluster Stuck in Provisioning

```bash
# Check BYOH controller logs
kubectl logs -n byoh-system deploy/byoh-controller-manager

# Check machine status
kubectl describe machines
```

---

# Troubleshooting Guide

This guide covers how to recover from a failed cluster creation attempt and how to properly delete clusters.

---

## Table of Contents

- [Recovering from a Failed Cluster Creation](#recovering-from-a-failed-cluster-creation)
- [Deleting a Cluster](#deleting-a-cluster)
- [Common Errors](#common-errors)

---

## Recovering from a Failed Cluster Creation

If a cluster creation attempt fails (e.g., Ansible job error, host timeout, CAPI provisioning stuck), follow these steps to clean up and retry.

### Step 1: Delete Kubernetes Resources from the Management Cluster

Run these commands on the **management cluster** to remove all resources related to the failed cluster:

```bash
# 1. Delete FocomProvisioningRequest
kubectl delete fpr --all

# 2. Delete ProvisioningRequests
kubectl delete provisioningrequests --all

# 3. Delete Clusters (if they were partially created)
kubectl delete clusters --all

# 4. Delete Machines (if any exist)
kubectl delete machines --all --ignore-not-found

# 5. Delete ByoHosts
kubectl delete byohosts --all
```

> [!TIP]
> If you only want to clean up a specific cluster (not all), replace `--all` with the specific resource name:
> ```bash
> kubectl delete fpr create-all-clusters
> kubectl delete provisioningrequest <cluster-name>-request
> kubectl delete cluster <cluster-name>
> kubectl delete byohost <host-name>
> ```

### Step 2: Clean Up the Target Nodes

SSH into **each target node** that was part of the failed cluster and run the following commands to fully reset it:

```bash
# --- Reset Kubernetes ---
sudo kubeadm reset -f

# --- Stop services ---
sudo pkill -f byoh-hostagent || true
sudo systemctl stop kubelet || true
sudo systemctl disable kubelet || true

# --- Remove Kubernetes files ---
sudo rm -rf \
  /etc/kubernetes \
  /var/lib/kubelet \
  /var/lib/etcd \
  /etc/cni/net.d \
  /opt/cni/bin

sudo rm -rf /etc/kubernetes/manifests || true

# --- Remove BYOH agent state ---
sudo rm -rf \
  /var/lib/byoh \
  /etc/byoh \
  /root/.byoh

# --- Remove old bootstrap kubeconfig ---
sudo rm -f /root/bootstrap-kubeconfig.conf
```

> [!IMPORTANT]
> You must run these cleanup commands on **every node** (masters and workers) that was involved in the failed attempt. If even one node has stale state, the retry will fail.

### Step 3: Retry Cluster Creation

Once all resources are cleaned up on the management cluster and all target nodes are reset:

```bash
# Re-apply the provisioning request
kubectl apply -f examples/focom-all-clusters.yaml

# Monitor progress
kubectl get fpr -w
kubectl get provisioningrequests -w
kubectl get clusters -w
```

The Ansible playbook will re-run automatically, re-register the hosts, and provision fresh clusters.

---

## Deleting a Cluster

To properly delete a running cluster, follow the same two-step process:

### Step 1: Delete Kubernetes Resources from the Management Cluster

```bash
# 1. Delete FocomProvisioningRequest (triggers cascade delete)
kubectl delete fpr --all

# 2. Delete ProvisioningRequests
kubectl delete provisioningrequests --all

# 3. Delete Clusters
kubectl delete clusters --all

# 4. Delete Machines (if any remain)
kubectl delete machines --all --ignore-not-found

# 5. Delete ByoHosts
kubectl delete byohosts --all
```

> [!TIP]
> To delete a specific cluster:
> ```bash
> kubectl delete fpr <fpr-name>
> kubectl delete provisioningrequest <cluster-name>-request
> kubectl delete cluster <cluster-name>
> kubectl delete byohost <host-name>
> ```

### Step 2: Clean Up the Target Nodes

SSH into **each node** that was part of the cluster and run:

```bash
# --- Reset Kubernetes ---
sudo kubeadm reset -f

# --- Stop services ---
sudo pkill -f byoh-hostagent || true
sudo systemctl stop kubelet || true
sudo systemctl disable kubelet || true

# --- Remove Kubernetes files ---
sudo rm -rf \
  /etc/kubernetes \
  /var/lib/kubelet \
  /var/lib/etcd \
  /etc/cni/net.d \
  /opt/cni/bin

sudo rm -rf /etc/kubernetes/manifests || true

# --- Remove BYOH agent state ---
sudo rm -rf \
  /var/lib/byoh \
  /etc/byoh \
  /root/.byoh

# --- Remove old bootstrap kubeconfig ---
sudo rm -f /root/bootstrap-kubeconfig.conf
```

After this, the nodes are clean and ready to be re-used for new cluster creation.

---

## Common Errors

### APT Lock Contention During Provisioning

**Error:** `Could not get lock /var/lib/dpkg/lock-frontend`

**Cause:** Ubuntu's background apt services (`apt-daily.timer`, `unattended-upgrades`) are holding package manager locks.

**Fix:** This is handled automatically by `site.yaml` which stops and disables all apt background services before any package installation. If you still encounter this, SSH into the node and run:

```bash
sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer unattended-upgrades
sudo systemctl disable apt-daily.timer apt-daily-upgrade.timer unattended-upgrades
sudo killall -9 apt-get apt dpkg 2>/dev/null || true
sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/cache/apt/archives/lock
sudo dpkg --configure -a
```

---

### ByoHost Stuck in "in-use" State

**Error:** BYOH controller cannot claim a host because it is still marked as "in-use" from a previous cluster.

**Fix:** Delete the ByoHost and clean the node:

```bash
# On management cluster
kubectl delete byohost <host-name>

# On the target node (SSH in)
sudo pkill -f byoh-hostagent || true
sudo rm -rf /var/lib/byoh /etc/byoh /root/.byoh
sudo rm -f /root/bootstrap-kubeconfig.conf
```

---

### Cluster Stuck in "Provisioning" State

**Cause:** The BYOH agent on the target node may have crashed or the kubeadm process failed partway.

**Fix:**
1. Check the BYOH agent logs on the target node:
   ```bash
   sudo cat /var/log/byoh.log
   ```
2. Check CAPI controller logs:
   ```bash
   kubectl logs -n byoh-system deploy/byoh-controller-manager
   ```
3. If stuck, follow the full [recovery procedure](#recovering-from-a-failed-cluster-creation) above.

---

### Ansible Job Keeps Failing

**Cause:** SSH connectivity issues, wrong credentials, or stale state on target nodes.

**Fix:**
1. Check Ansible job logs:
   ```bash
   kubectl get jobs -n o2ims-system
   kubectl logs job/<job-name> -n o2ims-system
   ```
2. Verify SSH access from management cluster:
   ```bash
   ssh <user>@<host-ip> "hostname"
   ```
3. Ensure `input.json` has correct `host_ip`, `host_user`, and `host_pwd` values.
4. If the node has stale state from a previous attempt, clean it up following [Step 2](#step-2-clean-up-the-target-nodes).

---

## Quick Reference: Full Cleanup Commands

### Management Cluster (copy-paste ready)

```bash
kubectl delete fpr --all
kubectl delete provisioningrequests --all
kubectl delete clusters --all
kubectl delete machines --all --ignore-not-found
kubectl delete byohosts --all
```

### Target Node (copy-paste ready)

```bash
sudo kubeadm reset -f
sudo pkill -f byoh-hostagent || true
sudo systemctl stop kubelet || true
sudo systemctl disable kubelet || true
sudo rm -rf /etc/kubernetes /var/lib/kubelet /var/lib/etcd /etc/cni/net.d /opt/cni/bin
sudo rm -rf /etc/kubernetes/manifests || true
sudo rm -rf /var/lib/byoh /etc/byoh /root/.byoh
sudo rm -f /root/bootstrap-kubeconfig.conf
```
