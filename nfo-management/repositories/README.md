# Configurable Git URLs for Porch

Porch needs **three** Git repositories:

| Variable | Role | Default |
|----------|------|---------|
| `NEPHFON_UPSTREAM_GIT` | This Nephfon repo (kpt packages under `/nfo-blueprints`) | `https://github.com/LFN-Super-Blueprints/nephfon.git` |
| `NEPHFON_RAN_DOWNSTREAM_GIT` | Empty Git repo Porch writes **rendered RAN** packages into | set in `repo-urls.env` |
| `NEPHFON_CORE_DOWNSTREAM_GIT` | Empty Git repo Porch writes **rendered core** packages into | set in `repo-urls.env` |

Downstream URLs are **not** this monorepo. Create two empty GitHub repos (or reuse existing ones), copy `repo-urls.env.example` to `repo-urls.env`, edit the URLs, then run:

```bash
cd nfo-management/repositories
cp repo-urls.env.example repo-urls.env
# edit repo-urls.env
./configure-repos.sh
```

That updates `upstream-repos.yaml`, `ran-downstream-repo.yaml`, `core-downstream-repo.yaml`, and the RootSync files under `../clusterconfig/`.
