# OAI RAN kpt packages

Packages in this tree:

- OAI RAN operator
- OAI CU-CP, CU-UP, DU
- OAI UE simulator (optional)
- OAI RAN network blueprint
- OAI CP operators (CRDs used by RAN NFs)

**Do not deploy these packages with the old catalog `package-variants/` YAMLs.** Nephfon applies them through Porch PackageVariants in this repository:

- Management CRs: [`nfo-management/packagevariants/oai-ran/`](../../../../nfo-management/packagevariants/oai-ran/)
- Deploy guide: [`nfo-management/README.md`](../../../../nfo-management/README.md)

Upstream Porch repo is this Nephfon Git repo with `directory: /nfo-blueprints` (see `nfo-management/repositories/`).
