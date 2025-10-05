# PowerShell script for Windows users to set up local Kubernetes in Docker
# This simulates Phase 1 of the Kubernetes deployment guide

Write-Host "=== Setting up Local Kubernetes in Docker (Windows) ===" -ForegroundColor Green

# Create Docker network
Write-Host "Creating Docker network..." -ForegroundColor Yellow
docker network create k8s-local-network 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Network already exists or error occurred" -ForegroundColor Gray
}

# Create Docker volumes
Write-Host "Creating Docker volumes..." -ForegroundColor Yellow
docker volume create k8s-local-data 2>$null
docker volume create k8s-etcd-data 2>$null
docker volume create k8s-kubelet-data 2>$null

# Create Dockerfile
Write-Host "Creating Dockerfile..." -ForegroundColor Yellow
@'
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

# Install basic utilities and systemd
RUN apt-get update && apt-get install -y \
    systemd \
    systemd-sysv \
    curl \
    wget \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    sudo \
    vim \
    net-tools \
    iproute2 \
    iptables \
    conntrack \
    socat \
    git \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Remove unnecessary systemd services for container
RUN cd /lib/systemd/system/sysinit.target.wants/ \
    && ls | grep -v systemd-tmpfiles-setup | xargs rm -f $1

RUN rm -f /lib/systemd/system/multi-user.target.wants/* \
    /etc/systemd/system/*.wants/* \
    /lib/systemd/system/local-fs.target.wants/* \
    /lib/systemd/system/sockets.target.wants/*udev* \
    /lib/systemd/system/sockets.target.wants/*initctl* \
    /lib/systemd/system/basic.target.wants/* \
    /lib/systemd/system/anaconda.target.wants/* \
    /lib/systemd/system/plymouth* \
    /lib/systemd/system/systemd-update-utmp*

# Install Docker (for container runtime)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add - \
    && add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    && apt-get update \
    && apt-get install -y docker-ce docker-ce-cli containerd.io \
    && rm -rf /var/lib/apt/lists/*

# Install Kubernetes components
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg \
    && echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update \
    && apt-get install -y kubelet kubeadm kubectl \
    && apt-mark hold kubelet kubeadm kubectl \
    && rm -rf /var/lib/apt/lists/*

# Configure kernel modules and sysctl
RUN echo "overlay" >> /etc/modules-load.d/k8s.conf \
    && echo "br_netfilter" >> /etc/modules-load.d/k8s.conf

RUN echo "net.bridge.bridge-nf-call-iptables  = 1" >> /etc/sysctl.d/k8s.conf \
    && echo "net.bridge.bridge-nf-call-ip6tables = 1" >> /etc/sysctl.d/k8s.conf \
    && echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.d/k8s.conf

# Configure containerd
RUN mkdir -p /etc/containerd \
    && containerd config default > /etc/containerd/config.toml \
    && sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml

# Create setup script
COPY setup-k8s.sh /usr/local/bin/setup-k8s.sh
RUN chmod +x /usr/local/bin/setup-k8s.sh

# Enable services
RUN systemctl enable docker containerd kubelet

VOLUME ["/sys/fs/cgroup", "/var/lib/docker"]

CMD ["/lib/systemd/systemd"]
'@ | Out-File -FilePath "Dockerfile.k8s-local" -Encoding UTF8

# Create setup script
Write-Host "Creating setup script..." -ForegroundColor Yellow
@'
#!/bin/bash

set -e

echo "=== Starting Kubernetes Setup Inside Container ==="

# Wait for systemd to be ready
sleep 5

# Load kernel modules
modprobe overlay || true
modprobe br_netfilter || true

# Apply sysctl params
sysctl --system

# Ensure services are running
systemctl restart docker
systemctl restart containerd
systemctl restart kubelet

# Disable swap
swapoff -a

# Get container IP
CONTAINER_IP=$(hostname -I | awk '{print $1}')
echo "Container IP: $CONTAINER_IP"

# Check if cluster is already initialized
if [ -f /etc/kubernetes/admin.conf ]; then
    echo "Kubernetes cluster already initialized"
    kubectl get nodes
else
    echo "Initializing Kubernetes cluster..."

    # Initialize Kubernetes cluster
    kubeadm init \
        --apiserver-advertise-address=$CONTAINER_IP \
        --pod-network-cidr=10.244.0.0/16 \
        --ignore-preflight-errors=all

    # Set up kubectl for root user
    export KUBECONFIG=/etc/kubernetes/admin.conf

    # Remove taint from master node to allow scheduling
    kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true

    # Install Flannel CNI
    kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

    # Wait for core pods to be ready
    echo "Waiting for system pods to be ready..."
    kubectl wait --for=condition=Ready pods --all -n kube-system --timeout=300s || true

    # Create kubeconfig for easier access
    mkdir -p /root/.kube
    cp -i /etc/kubernetes/admin.conf /root/.kube/config
    chown $(id -u):$(id -g) /root/.kube/config

    echo "=== Kubernetes cluster initialized successfully ==="
    kubectl get nodes
    kubectl get pods -A
fi

echo "=== Setup Complete ==="
echo "You can now use kubectl commands inside this container"
'@ | Out-File -FilePath "setup-k8s.sh" -Encoding UTF8 -NoNewline

# Build Docker image
Write-Host "Building Kubernetes node Docker image..." -ForegroundColor Yellow
docker build -t k8s-local-node:latest -f Dockerfile.k8s-local .

# Stop and remove existing container if it exists
Write-Host "Cleaning up existing container if any..." -ForegroundColor Yellow
docker stop k8s-local-master 2>$null
docker rm k8s-local-master 2>$null

# Run the container
Write-Host "Starting Kubernetes container..." -ForegroundColor Yellow
docker run -d `
    --name k8s-local-master `
    --hostname k8s-master `
    --network k8s-local-network `
    --privileged `
    --cgroupns=host `
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw `
    -v k8s-local-data:/var/lib/docker `
    -v k8s-etcd-data:/var/lib/etcd `
    -v k8s-kubelet-data:/var/lib/kubelet `
    --tmpfs /run `
    --tmpfs /run/lock `
    -p 6443:6443 `
    -p 30080:30080 `
    -p 30443:30443 `
    -p 30300:30300 `
    -p 30301:30301 `
    -p 30500:30500 `
    -p 30900:30900 `
    k8s-local-node:latest

Write-Host "Waiting for container to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

Write-Host "Running Kubernetes setup inside container..." -ForegroundColor Yellow
docker exec k8s-local-master /usr/local/bin/setup-k8s.sh

Write-Host ""
Write-Host "=== Local Kubernetes Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "To access your Kubernetes cluster:" -ForegroundColor Cyan
Write-Host "1. Get into the container: docker exec -it k8s-local-master bash" -ForegroundColor White
Write-Host "2. Use kubectl commands normally" -ForegroundColor White
Write-Host ""
Write-Host "To access from your host machine:" -ForegroundColor Cyan
Write-Host "1. Copy the kubeconfig:" -ForegroundColor White
Write-Host "   docker cp k8s-local-master:/etc/kubernetes/admin.conf $HOME\.kube\config-local" -ForegroundColor Gray
Write-Host "2. Set KUBECONFIG environment variable:" -ForegroundColor White
Write-Host "   `$env:KUBECONFIG = `"$HOME\.kube\config-local`"" -ForegroundColor Gray
Write-Host "3. Update the server address in the config to localhost:6443" -ForegroundColor White
Write-Host ""
Write-Host "To stop: docker stop k8s-local-master" -ForegroundColor Yellow
Write-Host "To remove: docker rm -f k8s-local-master" -ForegroundColor Yellow
Write-Host "To clean up volumes: docker volume rm k8s-local-data k8s-etcd-data k8s-kubelet-data" -ForegroundColor Yellow