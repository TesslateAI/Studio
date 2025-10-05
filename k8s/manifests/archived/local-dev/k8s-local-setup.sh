#!/bin/bash

# Script to set up Kubernetes in a Docker container for local testing
# This simulates Phase 1 of the Kubernetes deployment guide

set -e

echo "=== Setting up Local Kubernetes in Docker ==="

# Create a Docker network for Kubernetes
docker network create k8s-local-network 2>/dev/null || echo "Network already exists"

# Create a volume for persistent data
docker volume create k8s-local-data 2>/dev/null || echo "Volume already exists"

# Build the Dockerfile for our Kubernetes node
cat << 'EOF' > Dockerfile.k8s-local
FROM ubuntu:22.04

# Avoid interactive prompts during package installation
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

# Use systemd as init
CMD ["/lib/systemd/systemd"]
EOF

# Create the setup script that will run inside the container
cat << 'EOF' > setup-k8s.sh
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
echo "To access from outside, copy /etc/kubernetes/admin.conf"
EOF

# Build the Docker image
echo "Building Kubernetes node Docker image..."
docker build -t k8s-local-node:latest -f Dockerfile.k8s-local .

echo "=== Starting Kubernetes Container ==="
echo "This will run a full Ubuntu system with systemd and Kubernetes"

# Run the container with proper privileges for systemd and Kubernetes
docker run -d \
    --name k8s-local-master \
    --hostname k8s-master \
    --network k8s-local-network \
    --privileged \
    --cgroupns=host \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    -v k8s-local-data:/var/lib/docker \
    -v k8s-etcd-data:/var/lib/etcd \
    -v k8s-kubelet-data:/var/lib/kubelet \
    --tmpfs /run \
    --tmpfs /run/lock \
    -p 6443:6443 \
    -p 30080:30080 \
    -p 30443:30443 \
    -p 30300:30300 \
    -p 30301:30301 \
    -p 30500:30500 \
    -p 30900:30900 \
    k8s-local-node:latest

echo "Waiting for container to start..."
sleep 10

echo "Running Kubernetes setup inside container..."
docker exec k8s-local-master /usr/local/bin/setup-k8s.sh

echo ""
echo "=== Local Kubernetes Setup Complete ==="
echo ""
echo "To access your Kubernetes cluster:"
echo "1. Get into the container: docker exec -it k8s-local-master bash"
echo "2. Use kubectl commands normally"
echo ""
echo "To access from your host machine:"
echo "1. Copy the kubeconfig: docker cp k8s-local-master:/etc/kubernetes/admin.conf ~/.kube/config-local"
echo "2. Export KUBECONFIG: export KUBECONFIG=~/.kube/config-local"
echo "3. Update the server address in the config to localhost:6443"
echo ""
echo "To stop: docker stop k8s-local-master"
echo "To remove: docker rm -f k8s-local-master"
echo "To clean up: docker volume rm k8s-local-data k8s-etcd-data k8s-kubelet-data"