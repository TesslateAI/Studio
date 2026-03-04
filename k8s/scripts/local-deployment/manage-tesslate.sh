#!/bin/bash

# Tesslate Studio - Management Helper Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS_DIR="$(dirname "$SCRIPT_DIR")/manifests"

function show_help {
    cat <<EOF
Tesslate Studio Kubernetes Management

Usage: $0 <command> [options]

Commands:
    status          Show cluster and application status
    logs <service>  Show logs for a service (backend|frontend|postgres|registry)
    restart <service>  Restart a service
    scale <service> <replicas>  Scale a service
    update          Update application with latest manifests
    backup          Create database backup
    restore <file>  Restore database from backup
    clean           Remove all Tesslate resources
    port-forward    Set up local port forwarding
    secrets         Update application secrets

Examples:
    $0 status
    $0 logs backend
    $0 restart frontend
    $0 scale backend 3
    $0 backup
EOF
}

function check_kubectl {
    if ! kubectl cluster-info &> /dev/null; then
        echo "Error: kubectl is not configured or cluster is not accessible"
        exit 1
    fi
}

function show_status {
    echo "=== Tesslate Studio Status ==="
    echo ""
    echo "Nodes:"
    kubectl get nodes
    echo ""
    echo "Namespaces:"
    kubectl get namespaces | grep tesslate || echo "No Tesslate namespaces found"
    echo ""
    echo "Deployments:"
    kubectl get deployments -n tesslate 2>/dev/null || echo "No deployments in tesslate namespace"
    echo ""
    echo "Pods:"
    kubectl get pods -n tesslate 2>/dev/null || echo "No pods in tesslate namespace"
    echo ""
    echo "Services:"
    kubectl get services -n tesslate 2>/dev/null || echo "No services in tesslate namespace"
    echo ""
    echo "Ingress:"
    kubectl get ingress -n tesslate 2>/dev/null || echo "No ingress in tesslate namespace"
    echo ""
    echo "Registry:"
    kubectl get pods -n tesslate-registry 2>/dev/null || echo "No registry pods"
}

function show_logs {
    local service=$1
    case $service in
        backend)
            kubectl logs -f deployment/tesslate-backend -n tesslate
            ;;
        frontend)
            kubectl logs -f deployment/tesslate-frontend -n tesslate
            ;;
        postgres)
            kubectl logs -f deployment/postgres -n tesslate
            ;;
        registry)
            kubectl logs -f deployment/docker-registry -n tesslate-registry
            ;;
        *)
            echo "Unknown service: $service"
            echo "Available: backend, frontend, postgres, registry"
            exit 1
            ;;
    esac
}

function restart_service {
    local service=$1
    case $service in
        backend)
            kubectl rollout restart deployment/tesslate-backend -n tesslate
            kubectl rollout status deployment/tesslate-backend -n tesslate
            ;;
        frontend)
            kubectl rollout restart deployment/tesslate-frontend -n tesslate
            kubectl rollout status deployment/tesslate-frontend -n tesslate
            ;;
        postgres)
            echo "Warning: Restarting database will cause temporary downtime"
            read -p "Continue? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                kubectl rollout restart deployment/postgres -n tesslate
                kubectl rollout status deployment/postgres -n tesslate
            fi
            ;;
        *)
            echo "Unknown service: $service"
            exit 1
            ;;
    esac
}

function scale_service {
    local service=$1
    local replicas=$2

    if [ -z "$replicas" ]; then
        echo "Please specify number of replicas"
        exit 1
    fi

    case $service in
        backend)
            kubectl scale deployment/tesslate-backend --replicas=$replicas -n tesslate
            ;;
        frontend)
            kubectl scale deployment/tesslate-frontend --replicas=$replicas -n tesslate
            ;;
        *)
            echo "Cannot scale service: $service"
            exit 1
            ;;
    esac

    echo "Scaled $service to $replicas replicas"
}

function update_application {
    echo "Updating Tesslate Studio..."
    kubectl apply -f $MANIFESTS_DIR/base/
    kubectl apply -f $MANIFESTS_DIR/database/
    kubectl apply -f $MANIFESTS_DIR/app/
    kubectl apply -f $MANIFESTS_DIR/registry/
    echo "Update complete"
}

function backup_database {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="tesslate_backup_$timestamp.sql"

    echo "Creating database backup: $backup_file"
    kubectl exec deployment/postgres -n tesslate -- pg_dump -U tesslate_user tesslate > $backup_file
    echo "Backup saved to: $(pwd)/$backup_file"
}

function restore_database {
    local backup_file=$1

    if [ ! -f "$backup_file" ]; then
        echo "Backup file not found: $backup_file"
        exit 1
    fi

    echo "Warning: This will restore the database from $backup_file"
    read -p "Continue? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl exec -i deployment/postgres -n tesslate -- psql -U tesslate_user tesslate < $backup_file
        echo "Database restored from $backup_file"
    fi
}

function clean_all {
    echo "Warning: This will remove all Tesslate Studio resources from the cluster"
    read -p "Are you sure? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl delete namespace tesslate tesslate-registry tesslate-monitoring --ignore-not-found
        kubectl delete pv postgres-pv tesslate-projects-pv registry-pv --ignore-not-found
        echo "All Tesslate resources have been removed"
    fi
}

function port_forward {
    echo "Setting up port forwarding..."
    echo "  Frontend: http://localhost:3000"
    echo "  Backend: http://localhost:8005"
    echo "  PostgreSQL: localhost:5432"
    echo ""
    echo "Press Ctrl+C to stop"

    kubectl port-forward service/tesslate-frontend-service 3000:80 -n tesslate &
    kubectl port-forward service/tesslate-backend-service 8005:8005 -n tesslate &
    kubectl port-forward service/postgres 5432:5432 -n tesslate &

    wait
}

function update_secrets {
    echo "Updating application secrets..."
    echo "Enter new values (press Enter to keep current):"

    read -p "OpenAI API Key: " openai_key
    read -p "JWT Secret: " jwt_secret
    read -p "PostgreSQL Password: " pg_password

    if [ ! -z "$openai_key" ]; then
        kubectl patch secret tesslate-app-secrets -n tesslate --type='json' \
            -p='[{"op": "replace", "path": "/data/OPENAI_API_KEY", "value":"'$(echo -n $openai_key | base64)'"}]'
    fi

    if [ ! -z "$jwt_secret" ]; then
        kubectl patch secret tesslate-app-secrets -n tesslate --type='json' \
            -p='[{"op": "replace", "path": "/data/SECRET_KEY", "value":"'$(echo -n $jwt_secret | base64)'"}]'
    fi

    if [ ! -z "$pg_password" ]; then
        kubectl patch secret postgres-secret -n tesslate --type='json' \
            -p='[{"op": "replace", "path": "/data/POSTGRES_PASSWORD", "value":"'$(echo -n $pg_password | base64)'"}]'
    fi

    echo "Secrets updated. Restart services to apply changes."
}

# Main script
check_kubectl

case "${1:-help}" in
    status)
        show_status
        ;;
    logs)
        show_logs $2
        ;;
    restart)
        restart_service $2
        ;;
    scale)
        scale_service $2 $3
        ;;
    update)
        update_application
        ;;
    backup)
        backup_database
        ;;
    restore)
        restore_database $2
        ;;
    clean)
        clean_all
        ;;
    port-forward)
        port_forward
        ;;
    secrets)
        update_secrets
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac