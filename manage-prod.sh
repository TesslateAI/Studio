#!/bin/bash

# Tesslate Studio Production Management Script
# Usage: ./manage-prod.sh [command]

set -e

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.prod"

cd "$(dirname "$0")"

case "$1" in
  start)
    echo "🚀 Starting Tesslate Studio (Production)..."
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d
    echo "✅ Services started!"
    echo ""
    echo "Access points:"
    echo "  - Frontend: https://studio-demo.tesslate.com"
    echo "  - API: https://studio-demo.tesslate.com/api"
    echo "  - Traefik Dashboard: http://129.212.178.205:8080"
    ;;

  stop)
    echo "🛑 Stopping Tesslate Studio..."
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down
    echo "✅ Services stopped!"
    ;;

  restart)
    echo "🔄 Restarting Tesslate Studio..."
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE restart
    echo "✅ Services restarted!"
    ;;

  status)
    echo "📊 Tesslate Studio Status:"
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE ps
    ;;

  logs)
    SERVICE=${2:-}
    if [ -z "$SERVICE" ]; then
      docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs -f
    else
      docker logs -f tesslate-$SERVICE
    fi
    ;;

  rebuild)
    echo "🔨 Rebuilding and redeploying..."
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --build
    echo "✅ Rebuild complete!"
    ;;

  backup)
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
    echo "💾 Creating database backup: $BACKUP_FILE"
    docker exec tesslate-postgres pg_dump -U tesslate_user tesslate > $BACKUP_FILE
    echo "✅ Backup created: $BACKUP_FILE"
    ;;

  restore)
    if [ -z "$2" ]; then
      echo "❌ Please specify backup file: ./manage-prod.sh restore backup_YYYYMMDD_HHMMSS.sql"
      exit 1
    fi
    echo "📥 Restoring database from: $2"
    cat $2 | docker exec -i tesslate-postgres psql -U tesslate_user tesslate
    echo "✅ Database restored!"
    ;;

  shell)
    SERVICE=${2:-orchestrator}
    echo "🐚 Opening shell in tesslate-$SERVICE..."
    docker exec -it tesslate-$SERVICE /bin/sh
    ;;

  clean)
    echo "🧹 Cleaning up Docker resources..."
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down
    docker system prune -f
    echo "✅ Cleanup complete!"
    ;;

  update)
    echo "⬆️  Updating Tesslate Studio..."
    git pull
    docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d --build
    echo "✅ Update complete!"
    ;;

  health)
    echo "🏥 Health Check:"
    echo ""
    echo "Frontend:"
    curl -s -o /dev/null -w "  Status: %{http_code}\n" http://localhost/
    echo ""
    echo "Backend API:"
    curl -s -o /dev/null -w "  Status: %{http_code}\n" http://localhost/api/
    echo ""
    echo "Database:"
    docker exec tesslate-postgres pg_isready -U tesslate_user && echo "  Status: Healthy" || echo "  Status: Unhealthy"
    echo ""
    echo "Containers:"
    docker ps --format "  {{.Names}}: {{.Status}}"
    ;;

  *)
    echo "Tesslate Studio Production Management"
    echo ""
    echo "Usage: ./manage-prod.sh [command] [options]"
    echo ""
    echo "Commands:"
    echo "  start          - Start all services"
    echo "  stop           - Stop all services"
    echo "  restart        - Restart all services"
    echo "  status         - Show service status"
    echo "  logs [service] - Show logs (optionally for specific service)"
    echo "  rebuild        - Rebuild and redeploy all services"
    echo "  backup         - Create database backup"
    echo "  restore <file> - Restore database from backup"
    echo "  shell [service]- Open shell in container (default: orchestrator)"
    echo "  clean          - Clean up Docker resources"
    echo "  update         - Pull latest code and rebuild"
    echo "  health         - Run health check on all services"
    echo ""
    echo "Examples:"
    echo "  ./manage-prod.sh start"
    echo "  ./manage-prod.sh logs orchestrator"
    echo "  ./manage-prod.sh backup"
    echo "  ./manage-prod.sh restore backup_20251005_120000.sql"
    echo "  ./manage-prod.sh shell postgres"
    ;;
esac
