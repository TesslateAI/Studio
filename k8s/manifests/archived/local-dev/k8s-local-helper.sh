#!/bin/bash

# Helper script for managing local Kubernetes in Docker

case "$1" in
  start)
    echo "Starting Kubernetes container..."
    docker start k8s-local-master
    echo "Kubernetes container started"
    ;;

  stop)
    echo "Stopping Kubernetes container..."
    docker stop k8s-local-master
    echo "Kubernetes container stopped"
    ;;

  restart)
    echo "Restarting Kubernetes container..."
    docker restart k8s-local-master
    echo "Kubernetes container restarted"
    ;;

  shell)
    echo "Entering Kubernetes container shell..."
    docker exec -it k8s-local-master bash
    ;;

  logs)
    echo "Showing Kubernetes container logs..."
    docker logs k8s-local-master --tail 100 -f
    ;;

  status)
    echo "=== Container Status ==="
    docker ps -a | grep k8s-local-master
    echo ""
    echo "=== Kubernetes Status ==="
    docker exec k8s-local-master kubectl get nodes 2>/dev/null || echo "Cluster not ready"
    echo ""
    echo "=== System Pods ==="
    docker exec k8s-local-master kubectl get pods -n kube-system 2>/dev/null || echo "Cannot get pods"
    ;;

  setup-kubectl)
    echo "Setting up kubectl on host..."
    mkdir -p ~/.kube
    docker cp k8s-local-master:/etc/kubernetes/admin.conf ~/.kube/config-local

    # Get container IP
    CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' k8s-local-master)

    # Update the server address in the kubeconfig
    if [[ "$OSTYPE" == "darwin"* ]]; then
      # macOS
      sed -i '' "s|server: https://.*:6443|server: https://localhost:6443|g" ~/.kube/config-local
    else
      # Linux
      sed -i "s|server: https://.*:6443|server: https://localhost:6443|g" ~/.kube/config-local
    fi

    echo "Kubeconfig copied to ~/.kube/config-local"
    echo "To use it, run: export KUBECONFIG=~/.kube/config-local"
    ;;

  install-helm)
    echo "Installing Helm in the container..."
    docker exec k8s-local-master bash -c '
      curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | tee /usr/share/keyrings/helm.gpg > /dev/null
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | tee /etc/apt/sources.list.d/helm-stable-debian.list
      apt-get update
      apt-get install -y helm
    '
    echo "Helm installed successfully"
    ;;

  install-ingress)
    echo "Installing NGINX Ingress Controller..."
    docker exec k8s-local-master bash -c '
      helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
      helm repo update
      helm install ingress-nginx ingress-nginx/ingress-nginx \
        --namespace ingress-nginx \
        --create-namespace \
        --set controller.service.type=NodePort \
        --set controller.service.nodePorts.http=30080 \
        --set controller.service.nodePorts.https=30443
    '
    echo "NGINX Ingress Controller installed"
    ;;

  clean)
    echo "Cleaning up Kubernetes container and volumes..."
    docker stop k8s-local-master 2>/dev/null
    docker rm k8s-local-master 2>/dev/null
    docker volume rm k8s-local-data k8s-etcd-data k8s-kubelet-data 2>/dev/null
    docker network rm k8s-local-network 2>/dev/null
    rm -f ~/.kube/config-local
    echo "Cleanup complete"
    ;;

  test-app)
    echo "Deploying a test application..."
    docker exec k8s-local-master bash -c '
      kubectl create deployment nginx-test --image=nginx
      kubectl expose deployment nginx-test --port=80 --type=NodePort --name=nginx-service
      kubectl get services nginx-service
    '
    echo ""
    echo "Test application deployed. Get the NodePort and access at http://localhost:<nodeport>"
    ;;

  *)
    echo "Usage: $0 {start|stop|restart|shell|logs|status|setup-kubectl|install-helm|install-ingress|clean|test-app}"
    echo ""
    echo "Commands:"
    echo "  start          - Start the Kubernetes container"
    echo "  stop           - Stop the Kubernetes container"
    echo "  restart        - Restart the Kubernetes container"
    echo "  shell          - Enter container shell"
    echo "  logs           - Show container logs"
    echo "  status         - Show cluster status"
    echo "  setup-kubectl  - Configure kubectl on host machine"
    echo "  install-helm   - Install Helm package manager"
    echo "  install-ingress - Install NGINX Ingress Controller"
    echo "  clean          - Remove container and all volumes"
    echo "  test-app       - Deploy a test nginx application"
    exit 1
    ;;
esac