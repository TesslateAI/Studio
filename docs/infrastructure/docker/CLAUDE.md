# Docker Agent Context

Quick reference for Docker Compose development environment.

## File Locations

**Compose**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docker-compose.yml`
**Dockerfiles**: See [dockerfiles.md](dockerfiles.md)

## Quick Commands

```bash
# Start
docker-compose up -d

# Logs
docker-compose logs -f orchestrator

# Rebuild after code changes
docker-compose up -d --build orchestrator

# Reset database
docker-compose down -v && docker-compose up -d

# Shell access
docker-compose exec orchestrator bash
docker-compose exec app sh
docker-compose exec postgres psql -U tesslate_user -d tesslate_dev
```

## Hot Reload

**Backend**: Uvicorn watches `./orchestrator/app/`
**Frontend**: Vite HMR watches `./app/src/`

## Access

- Frontend: http://localhost
- API: http://localhost/api
- Traefik: http://localhost/traefik
- User projects: http://{container}.localhost

## Debugging

**Check service status**:
```bash
docker-compose ps
```

**View logs**:
```bash
docker-compose logs -f {service}
```

**Restart service**:
```bash
docker-compose restart {service}
```
