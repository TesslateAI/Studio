"""
Regional Traefik Router Service

This lightweight HTTP proxy sits between main Traefik and regional Traefiks.
It extracts the project slug from the hostname, hashes it to determine which
regional Traefik should handle the request, and proxies the request there.

Architecture:
  Internet → Main Traefik → THIS SERVICE → Regional Traefik → Container

This solves the problem of main Traefik not being able to do hash-based routing.
"""

import httpx
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration
PROJECTS_PER_REGIONAL = 250
REGIONAL_TRAEFIK_PORT = 80  # Internal port (not exposed to host)


def get_regional_index_for_project(project_slug: str) -> int:
    """
    Determine which regional Traefik should handle this project.
    Must match the logic in RegionalTraefikManager.
    """
    import hashlib
    hash_bytes = hashlib.md5(project_slug.encode()).digest()
    hash_value = int.from_bytes(hash_bytes[:4], byteorder='big')
    regional_index = hash_value % 100  # Support up to 100 regional Traefiks
    return regional_index


def extract_project_slug(hostname: str) -> str:
    """
    Extract project slug from hostname.

    The container name format from docker_compose_orchestrator.py is:
      sanitized_container_name = f"{project.slug}-{service_name}"

    Where service_name is the sanitized container.name (e.g., "next-js-15").

    Project slugs follow the pattern: {name}-{random-hash}
    Examples:
      fire-hpjvb0-next-js-15.localhost → fire-hpjvb0
      untitled-project-k3x8n2-frontend.localhost → untitled-project-k3x8n2
      my-app-abc123-backend.localhost → my-app-abc123

    Strategy: Look for the last short alphanumeric segment (5-8 chars) as the project hash,
    then everything before it (including that hash) is the project slug.
    """
    # Remove domain suffix (.localhost, .tesslate.com, etc.)
    parts = hostname.split('.')
    hostname_only = parts[0] if len(parts) > 1 else hostname

    # Split by hyphen
    segments = hostname_only.split('-')

    # Project slug pattern: ends with a short random hash (5-8 chars, alphanumeric)
    # Search backwards for a segment that looks like a slug hash
    for i in range(len(segments) - 1, -1, -1):
        segment = segments[i]
        # Check if this looks like a project slug hash:
        # - Length 5-8 characters
        # - Alphanumeric (lowercase letters + digits)
        # - Not all digits (to distinguish from ports like "3000")
        # - Not common container type words
        common_words = ['frontend', 'backend', 'api', 'web', 'app', 'next', 'nextjs',
                        'react', 'vite', 'js', 'ts', 'py', 'go', 'node', 'python']

        if (5 <= len(segment) <= 8 and
            segment.isalnum() and
            not segment.isdigit() and
            segment.lower() not in common_words and
            any(c.isalpha() for c in segment) and
            any(c.isdigit() for c in segment)):
            # Found the slug hash - project slug is everything up to and including this
            project_slug = '-'.join(segments[:i + 1])
            logger.debug(f"Extracted project slug '{project_slug}' from hostname '{hostname}'")
            return project_slug

    # Fallback: if no hash pattern found, take first 2 segments or all if less
    # This handles simple project names without the hash pattern
    project_slug = '-'.join(segments[:min(2, len(segments))])
    logger.debug(f"Extracted project slug '{project_slug}' from hostname '{hostname}' (fallback)")

    return project_slug


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_to_regional(request: Request, path: str):
    """
    Proxy all requests to the appropriate regional Traefik based on project hash.
    """
    # Get hostname from Host header
    hostname = request.headers.get("host", "")
    logger.info(f"[REGIONAL-ROUTER] Received request: {request.method} {hostname}/{path}")

    if not hostname:
        return Response(content="Missing Host header", status_code=400)

    # Extract project slug
    project_slug = extract_project_slug(hostname)

    # Determine regional Traefik
    regional_index = get_regional_index_for_project(project_slug)
    regional_traefik_url = f"http://tesslate-traefik-regional-{regional_index}:{REGIONAL_TRAEFIK_PORT}"

    logger.info(f"Routing {hostname} (project: {project_slug}) → Regional #{regional_index}")

    # Build target URL
    target_url = f"{regional_traefik_url}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Prepare headers (forward all except Host)
    headers = dict(request.headers)
    headers["host"] = hostname  # Keep original Host header for Traefik routing

    # Forward request to regional Traefik
    try:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)

        # Stream the request body
        body = await request.body()

        response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=30.0
        )

        # Clean up headers - remove hop-by-hop headers
        response_headers = {}
        hop_by_hop = [
            'connection', 'keep-alive', 'proxy-authenticate',
            'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade',
            'content-encoding', 'content-length'
        ]
        for key, value in response.headers.items():
            if key.lower() not in hop_by_hop:
                response_headers[key] = value

        # Return response with streaming
        async def generate():
            async for chunk in response.aiter_bytes():
                yield chunk
            await client.aclose()

        return StreamingResponse(
            generate(),
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type")
        )

    except httpx.ConnectError as e:
        logger.error(f"Failed to connect to {regional_traefik_url}: {e}")
        logger.error(f"Project: {project_slug}, Regional: {regional_index}")
        return Response(
            content=f"Container starting... Regional Traefik #{regional_index} initializing. Refresh in a few seconds.",
            status_code=503
        )
    except httpx.TimeoutException:
        logger.error(f"Timeout connecting to {regional_traefik_url}")
        return Response(
            content="Container timeout - please refresh the page",
            status_code=504
        )
    except Exception as e:
        logger.error(f"Error proxying request: {e}", exc_info=True)
        logger.error(f"Project: {project_slug}, Regional: {regional_index}, URL: {target_url}")
        return Response(
            content="Internal proxy error - check container logs",
            status_code=500
        )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "regional-router"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
