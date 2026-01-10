Safe Shutdown Procedure

# 1. Stop all dynamic user containers first
docker ps --filter "name=tesslate-dev-user" -q | xargs -r docker stop

# 2. Gracefully stop all production services
docker compose -f docker-compose.prod.yml down

# 3. (Optional) Backup database before upgrade
docker run --rm -v tesslate-postgres-data:/data -v $(pwd):/backup \
alpine tar czf /backup/postgres-backup-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .

For Upgrades (recommended sequence)

# 1. Pull latest code/changes
git pull origin main  # or your branch

# 2. Rebuild images with new code
docker compose -f docker-compose.prod.yml build

# 3. Bring services back up
docker compose -f docker-compose.prod.yml up -d

# 4. Verify all services are healthy
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f
