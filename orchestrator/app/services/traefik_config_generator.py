"""
Traefik Configuration Generator

Generates dynamic Traefik configuration to route requests from main Traefik
to regional Traefiks based on project slug hashing.

The main Traefik needs to forward requests like:
  http://project-123-container.localhost → Regional Traefik X → Container

Since Traefik doesn't natively support hash-based routing, we use a middleware
approach with dynamic file configuration.
