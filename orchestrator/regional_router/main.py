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

    Examples:
      untitled-project-123-abc-frontend.localhost → untitled-project-123-abc
      untitled-project-123-abc-frontend.tesslate.com → untitled-project-123-abc
    """
    # Remove domain suffix
    parts = hostname.split('.')
    if len(parts) > 1:
        # Remove .localhost or .tesslate.com
        hostname_only = parts[0]
    else:
        hostname_only = hostname

    # Hostname format: {project-slug}-{container-name}
    # We need to extract the project slug
    # Container names are sanitized (lowercase, hyphens only)
    # Project slugs are also sanitized the same way

    # The format is: {project-slug}-{container-name}
    # We need to find where the project slug ends and container name begins
    # For now, we'll use a simple heuristic:
    # Project slugs typically contain a timestamp or UUID-like pattern

    # Better approach: Look for known container type patterns
    # Common container suffixes: -nextjs-15, -react-vite, -python-flask, etc.

    # For MVP: Assume project slug is everything before the last known container type
    # But we don't have that info here...

    # BEST APPROACH: Project slug format is: {name}-{timestamp}-{hash}
    # So we look for the pattern: word-numbers-hash
    # Example: untitled-project-1763393020689-6lep5w

    # Split by hyphen and reconstruct project slug
    # This is a heuristic - in production you'd want a more robust method
    parts = hostname_only.split('-')

    # Find the project slug pattern: should have a timestamp (13 digits)
    project_slug_parts = []
    found_timestamp = False

    for i, part in enumerate(parts):
        project_slug_parts.append(part)
        # Check if this looks like a timestamp (10-13 digits)
        if part.isdigit() and 10 <= len(part) <= 13:
            found_timestamp = True
            # Include the next part (hash) if it exists
            if i + 1 < len(parts) and len(parts[i + 1]) <= 10:
                project_slug_parts.append(parts[i + 1])
            break

    if not found_timestamp:
        # Fallback: use first 3 parts or all if less
        project_slug_parts = parts[:min(3, len(parts))]

    project_slug = '-'.join(project_slug_parts)
    logger.debug(f"Extracted project slug '{project_slug}' from hostname '{hostname}'")

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
