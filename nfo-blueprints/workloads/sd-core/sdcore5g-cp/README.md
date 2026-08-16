# sdcore5g-cp

## Description
Package representing sdcore5g control plane NFs.

Package definition is based on [sdcore5g helm charts](https://github.com/omec-project/sdcore-helm-charts), 
and service level configuration is preserved as defined there.

### Network Functions (NFs)

sdcore5g project implements following NFs:


| NF | Description | local-config |
| --- | --- | --- |
| AMF | Access and Mobility Management Function | true |
| AUSF | Authentication Server Function | false |
| NRF | Network Repository Function | false |
| NSSF | Network Slice Selection Function | false |
| PCF | Policy Control Function | false |
| SMF | Session Management Function | true |
| UDM | Unified Data Management | false |
| UDR | Unified Data Repository | false |

also Database and Web UI is defined:

| Service | Description | local-config |
| --- | --- | --- |
| mongodb | Database to store sdcore5g data | false |
| webui | UI used to register UE | false |
| sim-app | Sim Onboarding Application | false |

Note: `local-config: true` indicates that this resources won't be deployed to the workload cluster

### Dependencies

- `mongodb` requires `Persistent Volume`. We need to assure that dynamic PV provisioning will be available on the cluster
- `NRF` should be running before other NFs will be instantiated
    - all NFs packages contain `wait-nrf` init-container
- `NRF` and `WEBUI` require DB
    - packages contain `wait-mongodb` init-container
- `WEBUI` service is exposed as `NodePort` 
    - will be used to register UE on the sdcore5g side
- Communication via `SBI` between NFs and communication with `mongodb` is defined using K8s `ClusterIP` services
    - it forces you to deploy all NFs on a single cluster or consider including `service mesh` in a multi-cluster scenario

## Usage

### Fetch the package
`kpt pkg get REPO_URI[.git]/PKG_PATH[@VERSION] sdcore5g-cp`

Details: https://kpt.dev/reference/cli/pkg/get/

### View package content
`kpt pkg tree sdcore5g-cp`

Details: https://kpt.dev/reference/cli/pkg/tree/

### Apply the package
```
kpt live init sdcore5g-cp
kpt live apply sdcore5g-cp --reconcile-timeout=2m --output=table
```

Details: https://kpt.dev/reference/cli/live/

