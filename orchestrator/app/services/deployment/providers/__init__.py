"""Deployment provider implementations."""

# Source-push providers
# Container-push providers
from .aws_container import AWSContainerProvider
from .azure_container import AzureContainerProvider
from .cloudflare import CloudflareWorkersProvider
from .deno_deploy import DenoDeployProvider

# DigitalOcean App Platform (source mode)
from .do_container import DigitalOceanContainerProvider

# Export providers
from .dockerhub_export import DockerHubExportProvider
from .download_export import DownloadExportProvider
from .firebase import FirebaseHostingProvider
from .fly import FlyProvider
from .gcp_container import GCPContainerProvider
from .ghcr_export import GHCRExportProvider
from .github_pages import GitHubPagesProvider
from .heroku import HerokuProvider
from .koyeb import KoyebProvider
from .netlify import NetlifyProvider
from .northflank import NorthflankProvider

# Git-repo-required providers
from .railway import RailwayProvider
from .render import RenderProvider
from .surge import SurgeProvider
from .vercel import VercelProvider
from .zeabur import ZeaburProvider

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
