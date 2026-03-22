"""Deployment provider implementations."""

# Source-push providers
from .cloudflare import CloudflareWorkersProvider
from .vercel import VercelProvider
from .netlify import NetlifyProvider
from .heroku import HerokuProvider
from .koyeb import KoyebProvider
from .zeabur import ZeaburProvider
from .surge import SurgeProvider
from .deno_deploy import DenoDeployProvider
from .firebase import FirebaseHostingProvider

# Git-repo-required providers
from .railway import RailwayProvider
from .render import RenderProvider
from .northflank import NorthflankProvider
from .github_pages import GitHubPagesProvider

# DigitalOcean App Platform (source mode)
from .do_container import DigitalOceanContainerProvider

# Container-push providers
from .aws_container import AWSContainerProvider
from .gcp_container import GCPContainerProvider
from .azure_container import AzureContainerProvider
from .fly import FlyProvider

# Export providers
from .dockerhub_export import DockerHubExportProvider
from .ghcr_export import GHCRExportProvider
from .download_export import DownloadExportProvider

__all__ = [
    # Source-push
    "CloudflareWorkersProvider",
    "VercelProvider",
    "NetlifyProvider",
    "HerokuProvider",
    "KoyebProvider",
    "ZeaburProvider",
    "SurgeProvider",
    "DenoDeployProvider",
    "FirebaseHostingProvider",
    # Git-repo-required
    "RailwayProvider",
    "RenderProvider",
    "NorthflankProvider",
    "GitHubPagesProvider",
    # Container-push
    "AWSContainerProvider",
    "GCPContainerProvider",
    "AzureContainerProvider",
    "DigitalOceanContainerProvider",
    "FlyProvider",
    # Export
    "DockerHubExportProvider",
    "GHCRExportProvider",
    "DownloadExportProvider",
]
