#!/bin/bash
# OpenSail - Kubernetes Management Script
# Manages the DigitalOcean Kubernetes deployment

set -e

NAMESPACE="tesslate"
USER_NAMESPACE="tesslate-user-environments"

case "$1" in
  status)
    echo "📊 OpenSail Status (Kubernetes)"
    echo ""
    echo "Main Application:"
    kubectl get all -n $NAMESPACE
    echo ""
    echo "User Environments:"
    kubectl get deployments,services,ingresses -n $USER_NAMESPACE
    ;;

  logs)
    SERVICE=${2:-backend}
    echo "📜 Logs for tesslate-$SERVICE:"
    kubectl logs -f -n $NAMESPACE -l app=tesslate-$SERVICE --tail=100
    ;;

  restart)
    SERVICE=${2:-backend}
    echo "🔄 Restarting tesslate-$SERVICE..."
    kubectl rollout restart deployment/tesslate-$SERVICE -n $NAMESPACE
    kubectl rollout status deployment/tesslate-$SERVICE -n $NAMESPACE --timeout=120s
    echo "✅ Service restarted!"
    ;;

  scale)
    SERVICE=${2}
    REPLICAS=${3}
    if [ -z "$SERVICE" ] || [ -z "$REPLICAS" ]; then
      echo "❌ Usage: ./manage-k8s.sh scale <service> <replicas>"
      echo "   Example: ./manage-k8s.sh scale backend 3"
      exit 1
    fi
    echo "📈 Scaling tesslate-$SERVICE to $REPLICAS replicas..."
    kubectl scale deployment/tesslate-$SERVICE -n $NAMESPACE --replicas=$REPLICAS
    echo "✅ Scaled!"
    ;;

  health)
    echo "🏥 Health Check:"
    echo ""
    echo "Backend Pods:"
    kubectl get pods -n $NAMESPACE -l app=tesslate-backend
    echo ""
    echo "Frontend Pods:"
    kubectl get pods -n $NAMESPACE -l app=tesslate-frontend
    echo ""
    echo "PostgreSQL:"
    kubectl get pods -n $NAMESPACE -l app=postgres
    echo ""
    echo "Ingress:"
    kubectl get ingress -n $NAMESPACE
    echo ""
    echo "Load Balancer:"
    kubectl get svc -n ingress-nginx
    ;;

  shell)
    SERVICE=${2:-backend}
    POD=$(kubectl get pod -n $NAMESPACE -l app=tesslate-$SERVICE -o jsonpath='{.items[0].metadata.name}')
    if [ -z "$POD" ]; then
      echo "❌ No pod found for service: tesslate-$SERVICE"
      exit 1
    fi
    echo "🐚 Opening shell in $POD..."
    kubectl exec -it -n $NAMESPACE $POD -- /bin/bash
    ;;

  db-shell)
    POD=$(kubectl get pod -n $NAMESPACE -l app=postgres -o jsonpath='{.items[0].metadata.name}')
    if [ -z "$POD" ]; then
      echo "❌ No postgres pod found"
      exit 1
    fi
    echo "🗄️  Opening PostgreSQL shell..."
    kubectl exec -it -n $NAMESPACE $POD -- psql -U tesslate_user tesslate
    ;;

  backup)
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
    POD=$(kubectl get pod -n $NAMESPACE -l app=postgres -o jsonpath='{.items[0].metadata.name}')
    if [ -z "$POD" ]; then
      echo "❌ No postgres pod found"
      exit 1
    fi
    echo "💾 Creating database backup: $BACKUP_FILE"
    kubectl exec -n $NAMESPACE $POD -- pg_dump -U tesslate_user tesslate > $BACKUP_FILE
    echo "✅ Backup created: $BACKUP_FILE"
    ;;

  restore)
    if [ -z "$2" ]; then
      echo "❌ Please specify backup file: ./manage-k8s.sh restore backup_YYYYMMDD_HHMMSS.sql"
      exit 1
    fi
    POD=$(kubectl get pod -n $NAMESPACE -l app=postgres -o jsonpath='{.items[0].metadata.name}')
    if [ -z "$POD" ]; then
      echo "❌ No postgres pod found"
      exit 1
    fi
    echo "📥 Restoring database from: $2"
    cat $2 | kubectl exec -i -n $NAMESPACE $POD -- psql -U tesslate_user tesslate
    echo "✅ Database restored!"
    ;;

  deploy)
    echo "🚀 Deploying OpenSail to Kubernetes..."
    cd "$(dirname "$0")/../k8s"
    ./scripts/deployment/deploy-all.sh
    echo "✅ Deployment complete!"
    ;;

  update)
    echo "⬆️  Updating OpenSail..."

    # Source DOCR_TOKEN from k8s/.env
    if [ -f "../k8s/.env" ]; then
      export $(cat ../k8s/.env | grep DOCR_TOKEN | xargs)
    else
      echo "❌ k8s/.env file not found. Cannot authenticate to registry."
      exit 1
    fi

    cd "$(dirname "$0")/.."

    # Build and push new images
    echo "Building and pushing new images..."
    ./k8s/scripts/deployment/build-push-images.sh

    # Restart deployments to pull new images
    echo "Restarting deployments..."
    kubectl rollout restart deployment/tesslate-backend -n $NAMESPACE
    kubectl rollout restart deployment/tesslate-frontend -n $NAMESPACE

    kubectl rollout status deployment/tesslate-backend -n $NAMESPACE --timeout=120s
    kubectl rollout status deployment/tesslate-frontend -n $NAMESPACE --timeout=120s

    echo "✅ Update complete!"
    ;;

  users)
    echo "👥 Active User Environments:"
    kubectl get deployments -n $USER_NAMESPACE -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,CREATED:.metadata.creationTimestamp
    ;;

  cleanup-users)
    echo "🧹 Cleaning up idle user environments..."
    ./scripts/cleanup-k8s.sh
    ;;

  ingress)
    echo "🌐 Ingress Configuration:"
    echo ""
    echo "Main Application:"
    kubectl describe ingress -n $NAMESPACE
    echo ""
    echo "User Environments:"
    kubectl get ingress -n $USER_NAMESPACE
    ;;

  *)
    echo "OpenSail - Kubernetes Management"
    echo ""
    echo "Usage: ./manage-k8s.sh [command] [options]"
    echo ""
    echo "Commands:"
    echo "  status              - Show all pods, services, and ingresses"
    echo "  logs [service]      - Show logs (default: backend)"
    echo "  restart [service]   - Restart a service (default: backend)"
    echo "  scale <svc> <count> - Scale a service to N replicas"
    echo "  health              - Run health check on all services"
    echo "  shell [service]     - Open shell in pod (default: backend)"
    echo "  db-shell            - Open PostgreSQL shell"
    echo "  backup              - Create database backup"
    echo "  restore <file>      - Restore database from backup"
    echo "  deploy              - Deploy complete application"
    echo "  update              - Build new images and update deployment"
    echo "  users               - List active user environments"
    echo "  cleanup-users       - Clean up idle user environments"
    echo "  ingress             - Show ingress configuration"
    echo ""
    echo "Examples:"
    echo "  ./manage-k8s.sh status"
    echo "  ./manage-k8s.sh logs backend"
    echo "  ./manage-k8s.sh restart frontend"
    echo "  ./manage-k8s.sh scale backend 3"
    echo "  ./manage-k8s.sh backup"
    echo "  ./manage-k8s.sh db-shell"
    ;;
esac
