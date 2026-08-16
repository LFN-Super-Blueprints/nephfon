#!/bin/bash
# Build and import the ansible-runner image for O2IMS automation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="ansible-runner:local"

echo "Building ansible-runner image..."
cd "$SCRIPT_DIR/ansible-runner"
docker build -t "$IMAGE_NAME" .

echo "Importing image to containerd..."
sudo ctr -n k8s.io images import <(docker save "$IMAGE_NAME")

echo "Done! Image $IMAGE_NAME is available."
echo ""
echo "To verify:"
echo "  sudo ctr -n k8s.io images ls | grep ansible-runner"
