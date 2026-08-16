#!/usr/bin/env bash
# Substitute Git URLs from repo-urls.env into Porch Repository and RootSync manifests.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${1:-$DIR/repo-urls.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  echo "Copy repo-urls.env.example to repo-urls.env and set the three Git URLs." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${NEPHFON_UPSTREAM_GIT:?}"
: "${NEPHFON_RAN_DOWNSTREAM_GIT:?}"
: "${NEPHFON_CORE_DOWNSTREAM_GIT:?}"

python3 - "$DIR" "$NEPHFON_UPSTREAM_GIT" "$NEPHFON_RAN_DOWNSTREAM_GIT" "$NEPHFON_CORE_DOWNSTREAM_GIT" <<'PY'
import pathlib, re, sys
d = pathlib.Path(sys.argv[1])
urls = {
    d / "upstream-repos.yaml": sys.argv[2],
    d / "ran-downstream-repo.yaml": sys.argv[3],
    d / "core-downstream-repo.yaml": sys.argv[4],
    d.parent / "clusterconfig" / "rootsync-ran.yaml": sys.argv[3],
    d.parent / "clusterconfig" / "rootsync-core.yaml": sys.argv[4],
}
pat = re.compile(r"^(\s*)repo:\s*.*$", re.M)
for path, url in urls.items():
    text = path.read_text()
    new, n = pat.subn(rf"\1repo: {url}", text, count=1)
    if n != 1:
        raise SystemExit(f"could not update repo: in {path}")
    path.write_text(new)
    print(f"updated {path} -> {url}")
PY
