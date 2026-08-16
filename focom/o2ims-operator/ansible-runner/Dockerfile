# Ansible Runner Container for O2IMS
# This container includes both Ansible and kubectl for host registration

FROM python:3.11-slim

# Install required packages
RUN apt-get update && apt-get install -y \
    openssh-client \
    curl \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

# Install Ansible
RUN pip install --no-cache-dir ansible paramiko jmespath kubernetes

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/v1.32.0/bin/linux/amd64/kubectl" \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/

# Create workspace directory
WORKDIR /workspace

# Set SSH options
ENV ANSIBLE_HOST_KEY_CHECKING=False
ENV ANSIBLE_FORCE_COLOR=true

# Default command
ENTRYPOINT ["ansible-playbook"]
