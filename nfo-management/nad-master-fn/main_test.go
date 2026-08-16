package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestVlanModeLeavesNADsUntouched(t *testing.T) {
	input := `apiVersion: fn.kpt.dev/v1alpha1
kind: ResourceList
functionConfig:
  apiVersion: v1
  kind: ConfigMap
  data:
    networking-mode: vlan
    n3-interface: ens1f0
items:
- apiVersion: k8s.cni.cncf.io/v1
  kind: NetworkAttachmentDefinition
  metadata:
    name: n3
    annotations:
      specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n3
  spec:
    config: '{"cniVersion":"0.3.1","plugins":[{"type":"macvlan","master":"ens3.6","mode":"bridge"}]}'
`

	var out bytes.Buffer
	if err := Process(strings.NewReader(input), &out); err != nil {
		t.Fatalf("Process: %v", err)
	}

	got := out.String()
	if !strings.Contains(got, `"master":"ens3.6"`) {
		t.Fatalf("vlan mode should preserve nad-fn master; got:\n%s", got)
	}
	if strings.Contains(got, `"master":"ens1f0"`) {
		t.Fatalf("vlan mode must not apply per-interface NIC overrides; got:\n%s", got)
	}
}

func TestNicModeReplacesMaster(t *testing.T) {
	input := `apiVersion: fn.kpt.dev/v1alpha1
kind: ResourceList
functionConfig:
  apiVersion: v1
  kind: ConfigMap
  data:
    networking-mode: nic
    n3-interface: ens1f0
items:
- apiVersion: k8s.cni.cncf.io/v1
  kind: NetworkAttachmentDefinition
  metadata:
    name: n3
    annotations:
      specializer.nephio.org/owner: req.nephio.org/v1alpha1.Interface.n3
  spec:
    config: '{"cniVersion":"0.3.1","plugins":[{"type":"macvlan","master":"ens3.6","mode":"bridge"}]}'
`

	var out bytes.Buffer
	if err := Process(strings.NewReader(input), &out); err != nil {
		t.Fatalf("Process: %v", err)
	}

	got := out.String()
	if !strings.Contains(got, `"master":"ens1f0"`) {
		t.Fatalf("nic mode should replace master with physical NIC; got:\n%s", got)
	}
}

func TestInvalidNetworkingModeFails(t *testing.T) {
	input := `apiVersion: fn.kpt.dev/v1alpha1
kind: ResourceList
functionConfig:
  apiVersion: v1
  kind: ConfigMap
  data:
    networking-mode: bridge
items: []
`

	var out bytes.Buffer
	if err := Process(strings.NewReader(input), &out); err == nil {
		t.Fatal("expected error for invalid networking-mode")
	}
}
