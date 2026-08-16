# Introduction

This repository contains Kpt packages and package variants for SDCore operators and network functions. Designed for [Nephio](https://nephio.org/) release 4 and SDCore v1.4.0.

The package-variants are designed to deploy Nephio R4 deployment.

# 2. How to deploy the topology on Nephio

## Step 0: Prerequisite

1. Make sure that you have a running core, core and edge cluster topology as defined in [nephio exercise](https://github.com/nephio-project/docs/tree/main/content/en/docs/guides/install-guides). 

```bash
git clone https://github.com/ios-mcn-smo/sdcore-packages.git
cd sdcore-packages
```

## Step 1 (Optional): Adding sdcore-packages repository in nephio repo list

```bash
kpt live init sdcore-repository
kpt live apply sdcore-repository
```

To verify the repository is on-boarded

```bash
kubectl get repositories | grep sdcore-packages
```

<details>
<summary>The output is similar to:</summary>

```console
NAME                      TYPE   CONTENT   DEPLOYMENT   READY   ADDRESS
sdcore-core-packages      git    Package   false        True    https://github.com/ios-mcn-smo/sdcore-packages
```
</details>

