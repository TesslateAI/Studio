#!/bin/bash
# Tesslate Studio - Kubernetes Cleanup Script
# Removes all user development environments and optionally resets the database

set -e

NAMESPACE="tesslate"
USER_NAMESPACE="tesslate-user-environments"

echo "======================================"
echo "Tesslate Studio - Kubernetes Cleanup"
echo "======================================"
echo ""
echo "This will clean up Kubernetes resources."
echo ""
echo "Options:"
echo "  1. Clean user environments only (safe)"
echo "  2. Clean user environments + reset database (DESTRUCTIVE)"
echo "  3. Cancel"
echo ""
read -p "Choose option (1/2/3): " choice

case $choice in
  1)
    echo ""
    echo "Cleaning up user development environments..."

    # Delete all user dev pods, services, and ingresses
    kubectl delete deployments,services,ingresses -n $USER_NAMESPACE --all

    echo "✅ User environments cleaned up!"
    echo ""
    echo "Note: Main application (backend, frontend, database) is still running."
    echo "Users can create new projects normally."
    ;;

  2)
    echo ""
    echo "⚠️  WARNING: This will DELETE ALL DATA including:"
    echo "  - All user projects"
    echo "  - All chat history"
    echo "  - All user accounts"
    echo "  - All user development environments"
    echo ""
    read -p "Type 'DELETE EVERYTHING' to confirm: " confirm

    if [ "$confirm" != "DELETE EVERYTHING" ]; then
      echo "Cancelled."
      exit 0
    fi

    echo ""
    echo "🧹 Starting complete cleanup..."

    # 1. Delete all user environments
    echo "Deleting user development environments..."
    kubectl delete deployments,services,ingresses -n $USER_NAMESPACE --all

    # 2. Reset database
    echo "Resetting database..."
    POD_NAME=$(kubectl get pod -n $NAMESPACE -l app=postgres -o jsonpath='{.items[0].metadata.name}')

    if [ -n "$POD_NAME" ]; then
      kubectl exec -n $NAMESPACE $POD_NAME -- psql -U tesslate_user -d tesslate -c "
        TRUNCATE TABLE messages CASCADE;
        TRUNCATE TABLE chats CASCADE;
        TRUNCATE TABLE project_files CASCADE;
        TRUNCATE TABLE projects CASCADE;
        TRUNCATE TABLE users CASCADE;
        TRUNCATE TABLE refresh_tokens CASCADE;
        TRUNCATE TABLE agent_command_logs CASCADE;
        TRUNCATE TABLE pod_access_logs CASCADE;
      "
      echo "✅ Database reset complete!"
    else
      echo "❌ Could not find postgres pod. Database not reset."
    fi

    # 3. Clean persistent volume data (optional - commented out for safety)
    # echo "Cleaning PVC data..."
    # kubectl delete pvc tesslate-projects-pvc -n $USER_NAMESPACE
    # kubectl apply -f k8s/manifests/user-environments/storage.yaml

    echo ""
    echo "✅ Complete cleanup finished!"
    echo ""
    echo "Next steps:"
    echo "1. Backend will restart automatically"
    echo "2. Create a new user account"
    echo "3. Start building fresh projects"
    ;;

  3)
    echo "Cancelled."
    exit 0
    ;;

  *)
    echo "Invalid option. Cancelled."
    exit 1
    ;;
esac

echo ""
echo "Cleanup complete! 🎉"
