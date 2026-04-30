"""
Seed deployment target marketplace items (item_type='deployment_target').

Creates MarketplaceAgent entries for all 22 supported deployment providers,
allowing them to appear in the marketplace sidebar and deployment target picker.

Can be run standalone or called from the startup seeder.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent
from ..services.marketplace_constants import TESSLATE_OFFICIAL_ID
from ..services.tesslate_account import get_or_create_tesslate_account

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deployment target marketplace items — one per supported provider
# ---------------------------------------------------------------------------

DEPLOYMENT_TARGETS = [
    # ── Source-push providers (upload files/source, provider builds) ──────
    {
        "name": "Vercel",
        "slug": "deploy-vercel",
        "description": "Deploy frontend and full-stack apps to Vercel with automatic builds and global CDN.",
        "long_description": (
            "Vercel is the platform for frontend developers, providing the speed and "
            "reliability innovators need to create at the moment of inspiration. "
            "Supports Next.js, React, Vue, Svelte, and more with zero-config deploys."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "▲",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "serverless", "vercel", "nextjs"],
        "features": ["Automatic builds", "Global CDN", "Serverless functions", "Preview deployments"],
        "config": {"provider_key": "vercel", "deployment_mode": "source", "brand_color": "#000000"},
    },
    {
        "name": "Netlify",
        "slug": "deploy-netlify",
        "description": "Deploy static sites and serverless functions to Netlify with continuous deployment.",
        "long_description": (
            "Netlify is an intuitive Git-based workflow and powerful serverless platform "
            "to build, deploy, and collaborate on web apps. Supports all major frontend "
            "frameworks with built-in CI/CD."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "◆",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "serverless", "netlify", "jamstack"],
        "features": ["Continuous deployment", "Serverless functions", "Edge handlers", "Form handling"],
        "config": {"provider_key": "netlify", "deployment_mode": "pre-built", "brand_color": "#00C7B7"},
    },
    {
        "name": "Cloudflare Pages",
        "slug": "deploy-cloudflare",
        "description": "Deploy to Cloudflare's global edge network with Workers and Pages.",
        "long_description": (
            "Cloudflare Pages is a JAMstack platform for frontend developers to collaborate "
            "and deploy websites. Combined with Cloudflare Workers, it enables full-stack "
            "applications at the edge."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🔥",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "edge", "cloudflare", "workers"],
        "features": ["Edge computing", "Global CDN", "Workers integration", "Unlimited bandwidth"],
        "config": {"provider_key": "cloudflare", "deployment_mode": "pre-built", "brand_color": "#F38020"},
    },
    {
        "name": "Railway",
        "slug": "deploy-railway",
        "description": "Deploy full-stack apps to Railway with automatic builds and managed infrastructure.",
        "long_description": (
            "Railway is a deployment platform where you can provision infrastructure, "
            "develop with that infrastructure locally, and then deploy to the cloud. "
            "Supports any language or framework with Nixpacks auto-detection."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🚂",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "railway", "paas"],
        "features": ["Auto-detection", "Managed databases", "Private networking", "Instant rollbacks"],
        "config": {"provider_key": "railway", "deployment_mode": "source", "brand_color": "#0B0D0E"},
    },
    {
        "name": "Heroku",
        "slug": "deploy-heroku",
        "description": "Deploy apps to Heroku's managed platform with add-ons and easy scaling.",
        "long_description": (
            "Heroku is a cloud platform as a service that lets companies build, deliver, "
            "monitor, and scale apps. Supports Node.js, Python, Java, Ruby, Go, and more "
            "with a rich ecosystem of add-ons."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🟣",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "heroku", "paas"],
        "features": ["Buildpacks", "Add-on marketplace", "Easy scaling", "Review apps"],
        "config": {"provider_key": "heroku", "deployment_mode": "source", "brand_color": "#430098"},
    },
    {
        "name": "Render",
        "slug": "deploy-render",
        "description": "Deploy web services, static sites, and databases to Render with auto-scaling.",
        "long_description": (
            "Render is a unified cloud to build and run all your apps and websites with "
            "free TLS certificates, global CDN, DDoS protection, private networks, and "
            "auto deploys from Git."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🔷",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "render", "paas"],
        "features": ["Auto-scaling", "Managed databases", "Free TLS", "Private networks"],
        "config": {"provider_key": "render", "deployment_mode": "source", "brand_color": "#46E3B7"},
    },
    {
        "name": "Koyeb",
        "slug": "deploy-koyeb",
        "description": "Deploy serverless apps globally on Koyeb with auto-scaling and edge deployment.",
        "long_description": (
            "Koyeb is a developer-friendly serverless platform to deploy apps globally. "
            "No ops, servers, or infrastructure management required. Deploy from Git or "
            "Docker with built-in autoscaling."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🟢",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "serverless", "koyeb", "global"],
        "features": ["Global deployment", "Auto-scaling", "Built-in service mesh", "Health checks"],
        "config": {"provider_key": "koyeb", "deployment_mode": "source", "brand_color": "#121212"},
    },
    {
        "name": "Zeabur",
        "slug": "deploy-zeabur",
        "description": "Deploy full-stack apps to Zeabur with one-click deployment and managed services.",
        "long_description": (
            "Zeabur is a platform that helps you deploy your services with one click. "
            "Supports any programming language and framework with automatic detection "
            "and configuration."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "⚡",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "zeabur", "serverless"],
        "features": ["One-click deploy", "Auto-detection", "Managed databases", "Serverless"],
        "config": {"provider_key": "zeabur", "deployment_mode": "source", "brand_color": "#6C5CE7"},
    },
    {
        "name": "Northflank",
        "slug": "deploy-northflank",
        "description": "Deploy and manage microservices on Northflank with Kubernetes-powered infrastructure.",
        "long_description": (
            "Northflank is a platform for deploying and managing microservices with "
            "powerful build pipelines, managed databases, and Kubernetes infrastructure. "
            "Supports Git-based and Docker-based deployments."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🔶",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "northflank", "kubernetes"],
        "features": ["Build pipelines", "Managed databases", "Job scheduling", "Kubernetes-native"],
        "config": {"provider_key": "northflank", "deployment_mode": "source", "brand_color": "#01E277"},
    },
    {
        "name": "Surge.sh",
        "slug": "deploy-surge",
        "description": "Publish static web projects to the web instantly with Surge.",
        "long_description": (
            "Surge is a simple, single-command web publishing tool. Publish HTML, CSS, "
            "and JS for free, with custom domain support and SSL certificates."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🌊",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "static", "surge"],
        "features": ["Instant publishing", "Custom domains", "Free SSL", "CLI deployment"],
        "config": {"provider_key": "surge", "deployment_mode": "pre-built", "brand_color": "#D93472"},
    },
    {
        "name": "Deno Deploy",
        "slug": "deploy-deno",
        "description": "Deploy JavaScript and TypeScript to Deno's global edge network.",
        "long_description": (
            "Deno Deploy is a distributed system that runs JavaScript, TypeScript, and "
            "WebAssembly at the edge, worldwide. Built on the Deno runtime with zero "
            "config deployments and instant rollbacks."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🦕",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "edge", "deno", "typescript", "serverless"],
        "features": ["Edge runtime", "TypeScript native", "Instant rollbacks", "V8 isolates"],
        "config": {"provider_key": "deno-deploy", "deployment_mode": "source", "brand_color": "#000000"},
    },
    {
        "name": "Firebase Hosting",
        "slug": "deploy-firebase",
        "description": "Deploy web apps to Firebase with global CDN and serverless backend integration.",
        "long_description": (
            "Firebase Hosting provides fast and secure hosting for your web app, static "
            "and dynamic content, and microservices. Backed by a global CDN with a free "
            "SSL certificate."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🔥",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "firebase", "google"],
        "features": ["Global CDN", "Free SSL", "Cloud Functions integration", "Preview channels"],
        "config": {"provider_key": "firebase", "deployment_mode": "pre-built", "brand_color": "#FFCA28"},
    },
    {
        "name": "GitHub Pages",
        "slug": "deploy-github-pages",
        "description": "Deploy static sites directly from your GitHub repository with GitHub Pages.",
        "long_description": (
            "GitHub Pages is a static site hosting service that takes files straight from "
            "a repository on GitHub and publishes a website. Perfect for project documentation, "
            "portfolios, and single-page applications."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "📄",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "frontend", "static", "github"],
        "features": ["Free hosting", "Custom domains", "HTTPS", "GitHub Actions integration"],
        "config": {"provider_key": "github-pages", "deployment_mode": "pre-built", "brand_color": "#222222"},
    },
    {
        "name": "DigitalOcean App Platform",
        "slug": "deploy-digitalocean",
        "description": "Deploy full-stack apps to DigitalOcean App Platform with managed infrastructure.",
        "long_description": (
            "DigitalOcean App Platform is a Platform-as-a-Service (PaaS) that allows "
            "developers to publish code directly to DigitalOcean servers without worrying "
            "about managing the underlying infrastructure."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🌊",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "fullstack", "digitalocean", "paas"],
        "features": ["Managed infrastructure", "Auto-scaling", "Built-in databases", "Global CDN"],
        "config": {"provider_key": "digitalocean", "deployment_mode": "source", "brand_color": "#0080FF"},
    },
    # ── Container-push providers ─────────────────────────────────────────
    {
        "name": "AWS App Runner",
        "slug": "deploy-aws-apprunner",
        "description": "Deploy containerized apps to AWS App Runner with automatic scaling and load balancing.",
        "long_description": (
            "AWS App Runner is a fully managed container application service that lets you "
            "build, deploy, and run containerized web applications and API services without "
            "prior infrastructure or container experience."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "☁️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "container", "aws", "apprunner", "cloud"],
        "features": ["Auto-scaling", "Load balancing", "VPC connectivity", "Managed TLS"],
        "config": {"provider_key": "aws-apprunner", "deployment_mode": "container", "brand_color": "#FF9900"},
    },
    {
        "name": "GCP Cloud Run",
        "slug": "deploy-gcp-cloudrun",
        "description": "Deploy containers to Google Cloud Run with serverless scaling and pay-per-use.",
        "long_description": (
            "Cloud Run is a managed compute platform that lets you run containers directly "
            "on top of Google's scalable infrastructure. It scales automatically from zero "
            "to N based on traffic."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "☁️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "container", "gcp", "cloudrun", "serverless"],
        "features": ["Scale to zero", "Pay per use", "gRPC support", "Custom domains"],
        "config": {"provider_key": "gcp-cloudrun", "deployment_mode": "container", "brand_color": "#4285F4"},
    },
    {
        "name": "Azure Container Apps",
        "slug": "deploy-azure-container-apps",
        "description": "Deploy microservices to Azure Container Apps with Dapr integration and auto-scaling.",
        "long_description": (
            "Azure Container Apps enables you to run microservices and containerized "
            "applications on a serverless platform. Built on Kubernetes and open-source "
            "technologies like Dapr, KEDA, and Envoy."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "☁️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "container", "azure", "microservices"],
        "features": ["Dapr integration", "KEDA auto-scaling", "Managed ingress", "Revision management"],
        "config": {"provider_key": "azure-container-apps", "deployment_mode": "container", "brand_color": "#0078D4"},
    },
    {
        "name": "DigitalOcean Container",
        "slug": "deploy-do-container",
        "description": "Deploy Docker containers to DigitalOcean App Platform with managed container runtime.",
        "long_description": (
            "Deploy pre-built Docker images to DigitalOcean's App Platform for a fully "
            "managed container experience. Includes auto-scaling, health checks, and "
            "zero-downtime deployments."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🌊",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "container", "digitalocean"],
        "features": ["Managed runtime", "Auto-scaling", "Health checks", "Zero-downtime deploys"],
        "config": {"provider_key": "do-container", "deployment_mode": "container", "brand_color": "#0080FF"},
    },
    {
        "name": "Fly.io",
        "slug": "deploy-fly",
        "description": "Deploy containers globally on Fly.io with edge computing and multi-region support.",
        "long_description": (
            "Fly.io runs your full-stack apps and databases close to your users. "
            "Deploy any Dockerfile to edge locations worldwide with built-in "
            "load balancing, auto-scaling, and private networking."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "✈️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "container", "fly", "edge", "global"],
        "features": ["Multi-region", "Edge computing", "Private networking", "GPU support"],
        "config": {"provider_key": "fly", "deployment_mode": "container", "brand_color": "#7B3FE4"},
    },
    # ── Export providers ─────────────────────────────────────────────────
    {
        "name": "Docker Hub",
        "slug": "deploy-dockerhub",
        "description": "Push container images to Docker Hub for distribution and sharing.",
        "long_description": (
            "Docker Hub is the world's largest container image library and community. "
            "Push your project images to Docker Hub for easy distribution, team sharing, "
            "and CI/CD integration."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "🐳",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "export", "docker", "registry"],
        "features": ["Public/private repos", "Automated builds", "Webhooks", "Team management"],
        "config": {"provider_key": "dockerhub", "deployment_mode": "export", "brand_color": "#2496ED"},
    },
    {
        "name": "GitHub Container Registry",
        "slug": "deploy-ghcr",
        "description": "Push container images to GitHub Container Registry for GitHub-native workflows.",
        "long_description": (
            "GitHub Container Registry (GHCR) stores container images within your GitHub "
            "organization or user account. Integrates natively with GitHub Actions and "
            "repository permissions."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "📦",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "export", "github", "registry", "ghcr"],
        "features": ["GitHub integration", "Fine-grained permissions", "Actions support", "Free for public images"],
        "config": {"provider_key": "ghcr", "deployment_mode": "export", "brand_color": "#222222"},
    },
    {
        "name": "Download Export",
        "slug": "deploy-download",
        "description": "Export your project as a downloadable archive for local use or manual deployment.",
        "long_description": (
            "Download your project files as a ZIP archive. Useful for local deployment, "
            "manual server uploads, or offline distribution without requiring any cloud "
            "provider credentials."
        ),
        "category": "deployment",
        "item_type": "deployment_target",
        "icon": "💾",
        "pricing_type": "free",
        "price": 0,
        "source_type": "closed",
        "is_forkable": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "export", "download", "offline"],
        "features": ["No credentials needed", "ZIP archive", "Offline use", "Manual deployment"],
        "config": {"provider_key": "download", "deployment_mode": "export", "brand_color": "#6B7280"},
    },
]


async def seed_deployment_targets(db: AsyncSession) -> int:
    """Seed deployment target marketplace items. Returns count of created items."""
    tesslate_user = await get_or_create_tesslate_account(db)
    created = 0
    updated = 0

    for target_data in DEPLOYMENT_TARGETS:
        slug = target_data["slug"]
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in target_data.items():
                if key != "slug":
                    setattr(existing, key, value)
            if not existing.source_id:
                existing.source_id = TESSLATE_OFFICIAL_ID
            updated += 1
            print(f"  [update] {slug}")
        else:
            agent = MarketplaceAgent(
                created_by_user_id=tesslate_user.id,
                source_id=TESSLATE_OFFICIAL_ID,
                **target_data,
            )
            db.add(agent)
            created += 1
            print(f"  [create] {slug}")

    await db.commit()
    print(f"  Total: {created} created, {updated} updated")
    return created
