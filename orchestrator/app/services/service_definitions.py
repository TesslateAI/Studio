"""
Service Definitions

Pre-configured services that users can drag into their projects.
These include:
1. Container services - Docker-based services (databases, caches, queues)
2. External services - Cloud services like Supabase, PlanetScale (no container)
3. Hybrid services - Can run either as container or connect to cloud

Each service has:
- Docker image (for container-based)
- Default environment variables
- Exposed ports
- Volume configuration (for data persistence)
- Health checks
- Credential fields (for external services)
- Connection templates (how env vars are generated from credentials)
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class ServiceType(str, Enum):
    """Type of service deployment"""
    CONTAINER = "container"  # Runs in Docker container
    EXTERNAL = "external"    # External cloud service (no container)
    HYBRID = "hybrid"        # Can run either way


class AuthType(str, Enum):
    """Authentication method for external services"""
    API_KEY = "api_key"
    OAUTH = "oauth"
    BEARER = "bearer"
    BASIC = "basic"
    CONNECTION_STRING = "connection_string"


@dataclass
class CredentialField:
    """Defines a credential field required by an external service"""
    key: str  # Internal key (e.g., "api_key", "project_url")
    label: str  # Display label (e.g., "API Key", "Project URL")
    type: str = "password"  # Input type: "text", "password", "url"
    required: bool = True
    placeholder: str = ""
    help_text: str = ""


@dataclass
class ServiceDefinition:
    """Defines a draggable service (container, external, or hybrid)"""
    slug: str
    name: str
    description: str
    category: str  # database, cache, queue, proxy, search, storage, baas, ai, payments, auth
    icon: str  # Emoji icon for the service

    # Service type
    service_type: ServiceType = ServiceType.CONTAINER

    # Container configuration (for container and hybrid types)
    docker_image: str = ""
    default_port: Optional[int] = None
    internal_port: Optional[int] = None
    environment_vars: Dict[str, str] = field(default_factory=dict)
    volumes: List[str] = field(default_factory=list)
    health_check: Optional[Dict[str, Any]] = None
    command: Optional[List[str]] = None

    # External service configuration
    credential_fields: List[CredentialField] = field(default_factory=list)
    auth_type: Optional[AuthType] = None
    oauth_provider: Optional[str] = None  # For OAuth-based services
    docs_url: Optional[str] = None

    # Connection template - how to generate env vars from credentials
    # Keys are target env var names, values are templates like "{api_key}" or "{project_url}/rest/v1"
    connection_template: Dict[str, str] = field(default_factory=dict)

    # Outputs - what this service provides to connected nodes
    # Keys are output names, values are descriptions
    outputs: Dict[str, str] = field(default_factory=dict)


# Service catalog
SERVICES: Dict[str, ServiceDefinition] = {
    # ============================================================================
    # CONTAINER SERVICES (run in Docker)
    # ============================================================================

    # Databases
    "postgres": ServiceDefinition(
        slug="postgres",
        name="PostgreSQL",
        description="PostgreSQL 16 - Powerful open-source relational database",
        category="database",
        icon="🐘",
        service_type=ServiceType.CONTAINER,
        docker_image="postgres:16-alpine",
        default_port=5432,
        internal_port=5432,
        environment_vars={
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "POSTGRES_DB": "app",
            "PGDATA": "/var/lib/postgresql/data/pgdata"
        },
        volumes=["/var/lib/postgresql/data"],
        health_check={
            "test": ["CMD-SHELL", "pg_isready -U postgres"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "DATABASE_URL": "PostgreSQL connection string",
            "POSTGRES_HOST": "Database hostname",
            "POSTGRES_PORT": "Database port",
            "POSTGRES_USER": "Database user",
            "POSTGRES_PASSWORD": "Database password",
            "POSTGRES_DB": "Database name"
        },
        connection_template={
            "DATABASE_URL": "postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{container_name}:{internal_port}/{POSTGRES_DB}",
            "POSTGRES_HOST": "{container_name}",
            "POSTGRES_PORT": "{internal_port}"
        }
    ),

    "mysql": ServiceDefinition(
        slug="mysql",
        name="MySQL",
        description="MySQL 8 - World's most popular open-source database",
        category="database",
        icon="🐬",
        service_type=ServiceType.CONTAINER,
        docker_image="mysql:8-oracle",
        default_port=3306,
        internal_port=3306,
        environment_vars={
            "MYSQL_ROOT_PASSWORD": "root",
            "MYSQL_DATABASE": "app",
            "MYSQL_USER": "app",
            "MYSQL_PASSWORD": "password"
        },
        volumes=["/var/lib/mysql"],
        health_check={
            "test": ["CMD", "mysqladmin", "ping", "-h", "localhost"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "DATABASE_URL": "MySQL connection string",
            "MYSQL_HOST": "Database hostname",
            "MYSQL_PORT": "Database port"
        },
        connection_template={
            "DATABASE_URL": "mysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{container_name}:{internal_port}/{MYSQL_DATABASE}",
            "MYSQL_HOST": "{container_name}",
            "MYSQL_PORT": "{internal_port}"
        }
    ),

    "mongodb": ServiceDefinition(
        slug="mongodb",
        name="MongoDB",
        description="MongoDB 7 - Document-oriented NoSQL database",
        category="database",
        icon="🍃",
        service_type=ServiceType.CONTAINER,
        docker_image="mongo:7",
        default_port=27017,
        internal_port=27017,
        environment_vars={
            "MONGO_INITDB_ROOT_USERNAME": "root",
            "MONGO_INITDB_ROOT_PASSWORD": "password",
            "MONGO_INITDB_DATABASE": "app"
        },
        volumes=["/data/db"],
        health_check={
            "test": ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "MONGODB_URL": "MongoDB connection string",
            "MONGODB_HOST": "Database hostname"
        },
        connection_template={
            "MONGODB_URL": "mongodb://{MONGO_INITDB_ROOT_USERNAME}:{MONGO_INITDB_ROOT_PASSWORD}@{container_name}:{internal_port}/{MONGO_INITDB_DATABASE}?authSource=admin",
            "MONGODB_HOST": "{container_name}"
        }
    ),

    # Cache
    "redis": ServiceDefinition(
        slug="redis",
        name="Redis",
        description="Redis 7 - In-memory data structure store",
        category="cache",
        icon="🔴",
        service_type=ServiceType.CONTAINER,
        docker_image="redis:7-alpine",
        default_port=6379,
        internal_port=6379,
        environment_vars={},
        volumes=["/data"],
        command=["redis-server", "--appendonly", "yes"],
        health_check={
            "test": ["CMD", "redis-cli", "ping"],
            "interval": "5s",
            "timeout": "3s",
            "retries": 5
        },
        outputs={
            "REDIS_URL": "Redis connection string",
            "REDIS_HOST": "Redis hostname",
            "REDIS_PORT": "Redis port"
        },
        connection_template={
            "REDIS_URL": "redis://{container_name}:{internal_port}",
            "REDIS_HOST": "{container_name}",
            "REDIS_PORT": "{internal_port}"
        }
    ),

    # Message Queues
    "rabbitmq": ServiceDefinition(
        slug="rabbitmq",
        name="RabbitMQ",
        description="RabbitMQ - Message broker with management UI",
        category="queue",
        icon="🐰",
        service_type=ServiceType.CONTAINER,
        docker_image="rabbitmq:3-management-alpine",
        default_port=5672,
        internal_port=5672,
        environment_vars={
            "RABBITMQ_DEFAULT_USER": "admin",
            "RABBITMQ_DEFAULT_PASS": "password"
        },
        volumes=["/var/lib/rabbitmq"],
        health_check={
            "test": ["CMD", "rabbitmq-diagnostics", "ping"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "RABBITMQ_URL": "AMQP connection string",
            "RABBITMQ_HOST": "RabbitMQ hostname"
        },
        connection_template={
            "RABBITMQ_URL": "amqp://{RABBITMQ_DEFAULT_USER}:{RABBITMQ_DEFAULT_PASS}@{container_name}:{internal_port}",
            "RABBITMQ_HOST": "{container_name}"
        }
    ),

    # Search
    "elasticsearch": ServiceDefinition(
        slug="elasticsearch",
        name="Elasticsearch",
        description="Elasticsearch 8 - Distributed search and analytics engine",
        category="search",
        icon="🔍",
        service_type=ServiceType.CONTAINER,
        docker_image="docker.elastic.co/elasticsearch/elasticsearch:8.11.0",
        default_port=9200,
        internal_port=9200,
        environment_vars={
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
            "ES_JAVA_OPTS": "-Xms512m -Xmx512m"
        },
        volumes=["/usr/share/elasticsearch/data"],
        health_check={
            "test": ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "ELASTICSEARCH_URL": "Elasticsearch URL",
            "ELASTICSEARCH_HOST": "Elasticsearch hostname"
        },
        connection_template={
            "ELASTICSEARCH_URL": "http://{container_name}:{internal_port}",
            "ELASTICSEARCH_HOST": "{container_name}"
        }
    ),

    # Storage
    "minio": ServiceDefinition(
        slug="minio",
        name="MinIO",
        description="MinIO - S3-compatible object storage",
        category="storage",
        icon="📦",
        service_type=ServiceType.CONTAINER,
        docker_image="minio/minio:latest",
        default_port=9000,
        internal_port=9000,
        environment_vars={
            "MINIO_ROOT_USER": "admin",
            "MINIO_ROOT_PASSWORD": "password123"
        },
        volumes=["/data"],
        command=["server", "/data", "--console-address", ":9001"],
        health_check={
            "test": ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        },
        outputs={
            "S3_ENDPOINT": "S3-compatible endpoint URL",
            "S3_ACCESS_KEY": "Access key",
            "S3_SECRET_KEY": "Secret key"
        },
        connection_template={
            "S3_ENDPOINT": "http://{container_name}:{internal_port}",
            "S3_ACCESS_KEY": "{MINIO_ROOT_USER}",
            "S3_SECRET_KEY": "{MINIO_ROOT_PASSWORD}"
        }
    ),

    # Proxy/Web Server
    "nginx": ServiceDefinition(
        slug="nginx",
        name="Nginx",
        description="Nginx - High-performance web server and reverse proxy",
        category="proxy",
        icon="🌐",
        service_type=ServiceType.CONTAINER,
        docker_image="nginx:alpine",
        default_port=80,
        internal_port=80,
        environment_vars={},
        volumes=["/usr/share/nginx/html", "/etc/nginx/conf.d"],
        health_check={
            "test": ["CMD-SHELL", "curl -f http://localhost/ || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3
        },
        outputs={
            "NGINX_URL": "Nginx URL"
        },
        connection_template={
            "NGINX_URL": "http://{container_name}:{internal_port}"
        }
    ),

    # ============================================================================
    # EXTERNAL SERVICES (cloud services, no container)
    # ============================================================================

    # Supabase - Backend as a Service
    "supabase": ServiceDefinition(
        slug="supabase",
        name="Supabase",
        description="Open-source Firebase alternative with PostgreSQL, Auth, Storage, and Realtime",
        category="baas",
        icon="⚡",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://supabase.com/docs",
        credential_fields=[
            CredentialField(
                key="project_url",
                label="Project URL",
                type="url",
                placeholder="https://xxxxx.supabase.co",
                help_text="Your Supabase project URL (found in Project Settings > API)"
            ),
            CredentialField(
                key="anon_key",
                label="Anon/Public Key",
                type="password",
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                help_text="Public anonymous key for client-side usage"
            ),
            CredentialField(
                key="service_role_key",
                label="Service Role Key",
                type="password",
                required=False,
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                help_text="Secret service role key for server-side usage (keep secret!)"
            ),
        ],
        outputs={
            "SUPABASE_URL": "Supabase project URL",
            "SUPABASE_ANON_KEY": "Public anonymous key",
            "SUPABASE_SERVICE_ROLE_KEY": "Service role key (server-side only)",
            "DATABASE_URL": "Direct PostgreSQL connection string"
        },
        connection_template={
            "SUPABASE_URL": "{project_url}",
            "SUPABASE_ANON_KEY": "{anon_key}",
            "SUPABASE_SERVICE_ROLE_KEY": "{service_role_key}",
            "NEXT_PUBLIC_SUPABASE_URL": "{project_url}",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "{anon_key}"
        }
    ),

    # PlanetScale - Serverless MySQL
    "planetscale": ServiceDefinition(
        slug="planetscale",
        name="PlanetScale",
        description="Serverless MySQL platform with branching and zero-downtime schema changes",
        category="database",
        icon="🌍",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.CONNECTION_STRING,
        docs_url="https://planetscale.com/docs",
        credential_fields=[
            CredentialField(
                key="connection_string",
                label="Connection String",
                type="password",
                placeholder="mysql://user:password@host/database?ssl={'rejectUnauthorized':true}",
                help_text="Full connection string from PlanetScale dashboard"
            ),
        ],
        outputs={
            "DATABASE_URL": "MySQL connection string"
        },
        connection_template={
            "DATABASE_URL": "{connection_string}"
        }
    ),

    # Neon - Serverless PostgreSQL
    "neon": ServiceDefinition(
        slug="neon",
        name="Neon",
        description="Serverless PostgreSQL with branching, autoscaling, and bottomless storage",
        category="database",
        icon="🟢",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.CONNECTION_STRING,
        docs_url="https://neon.tech/docs",
        credential_fields=[
            CredentialField(
                key="connection_string",
                label="Connection String",
                type="password",
                placeholder="postgresql://user:password@host/database?sslmode=require",
                help_text="Full connection string from Neon console"
            ),
        ],
        outputs={
            "DATABASE_URL": "PostgreSQL connection string"
        },
        connection_template={
            "DATABASE_URL": "{connection_string}"
        }
    ),

    # Upstash - Serverless Redis/Kafka
    "upstash": ServiceDefinition(
        slug="upstash",
        name="Upstash Redis",
        description="Serverless Redis with global replication and per-request pricing",
        category="cache",
        icon="🔺",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://upstash.com/docs/redis",
        credential_fields=[
            CredentialField(
                key="redis_url",
                label="Redis REST URL",
                type="url",
                placeholder="https://xxxxx.upstash.io",
                help_text="REST API URL from Upstash console"
            ),
            CredentialField(
                key="redis_token",
                label="Redis REST Token",
                type="password",
                placeholder="AXxxxx...",
                help_text="REST API token for authentication"
            ),
        ],
        outputs={
            "UPSTASH_REDIS_REST_URL": "Redis REST API URL",
            "UPSTASH_REDIS_REST_TOKEN": "Redis REST API token"
        },
        connection_template={
            "UPSTASH_REDIS_REST_URL": "{redis_url}",
            "UPSTASH_REDIS_REST_TOKEN": "{redis_token}",
            "KV_REST_API_URL": "{redis_url}",
            "KV_REST_API_TOKEN": "{redis_token}"
        }
    ),

    # OpenAI
    "openai": ServiceDefinition(
        slug="openai",
        name="OpenAI",
        description="GPT-4, GPT-3.5, DALL-E, Whisper, and Embeddings APIs",
        category="ai",
        icon="🤖",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://platform.openai.com/docs",
        credential_fields=[
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="sk-...",
                help_text="Your OpenAI API key"
            ),
        ],
        outputs={
            "OPENAI_API_KEY": "OpenAI API key"
        },
        connection_template={
            "OPENAI_API_KEY": "{api_key}"
        }
    ),

    # Anthropic
    "anthropic": ServiceDefinition(
        slug="anthropic",
        name="Anthropic",
        description="Claude AI models - powerful, safe, and steerable AI",
        category="ai",
        icon="🧠",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://docs.anthropic.com",
        credential_fields=[
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="sk-ant-...",
                help_text="Your Anthropic API key"
            ),
        ],
        outputs={
            "ANTHROPIC_API_KEY": "Anthropic API key"
        },
        connection_template={
            "ANTHROPIC_API_KEY": "{api_key}"
        }
    ),

    # Stripe
    "stripe": ServiceDefinition(
        slug="stripe",
        name="Stripe",
        description="Payment processing, subscriptions, and billing infrastructure",
        category="payments",
        icon="💳",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://stripe.com/docs",
        credential_fields=[
            CredentialField(
                key="secret_key",
                label="Secret Key",
                type="password",
                placeholder="sk_test_...",
                help_text="Your Stripe secret key (starts with sk_test_ or sk_live_)"
            ),
            CredentialField(
                key="publishable_key",
                label="Publishable Key",
                type="text",
                placeholder="pk_test_...",
                help_text="Your Stripe publishable key (safe for frontend)"
            ),
            CredentialField(
                key="webhook_secret",
                label="Webhook Secret",
                type="password",
                required=False,
                placeholder="whsec_...",
                help_text="Webhook signing secret (optional)"
            ),
        ],
        outputs={
            "STRIPE_SECRET_KEY": "Stripe secret key",
            "STRIPE_PUBLISHABLE_KEY": "Stripe publishable key",
            "STRIPE_WEBHOOK_SECRET": "Webhook signing secret"
        },
        connection_template={
            "STRIPE_SECRET_KEY": "{secret_key}",
            "STRIPE_PUBLISHABLE_KEY": "{publishable_key}",
            "STRIPE_WEBHOOK_SECRET": "{webhook_secret}",
            "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY": "{publishable_key}"
        }
    ),

    # Resend
    "resend": ServiceDefinition(
        slug="resend",
        name="Resend",
        description="Modern email API for developers - transactional emails made easy",
        category="email",
        icon="📧",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://resend.com/docs",
        credential_fields=[
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="re_...",
                help_text="Your Resend API key"
            ),
        ],
        outputs={
            "RESEND_API_KEY": "Resend API key"
        },
        connection_template={
            "RESEND_API_KEY": "{api_key}"
        }
    ),

    # Clerk
    "clerk": ServiceDefinition(
        slug="clerk",
        name="Clerk",
        description="Complete user management - authentication, user profiles, and organizations",
        category="auth",
        icon="🔐",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://clerk.com/docs",
        credential_fields=[
            CredentialField(
                key="publishable_key",
                label="Publishable Key",
                type="text",
                placeholder="pk_test_...",
                help_text="Frontend publishable key"
            ),
            CredentialField(
                key="secret_key",
                label="Secret Key",
                type="password",
                placeholder="sk_test_...",
                help_text="Backend secret key"
            ),
        ],
        outputs={
            "CLERK_PUBLISHABLE_KEY": "Clerk publishable key",
            "CLERK_SECRET_KEY": "Clerk secret key"
        },
        connection_template={
            "CLERK_PUBLISHABLE_KEY": "{publishable_key}",
            "CLERK_SECRET_KEY": "{secret_key}",
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "{publishable_key}"
        }
    ),

    # n8n - Workflow Automation
    "n8n": ServiceDefinition(
        slug="n8n",
        name="n8n",
        description="Workflow automation platform - connect apps and automate tasks",
        category="automation",
        icon="🔄",
        service_type=ServiceType.HYBRID,
        # Container config (self-hosted)
        docker_image="n8nio/n8n:latest",
        default_port=5678,
        internal_port=5678,
        environment_vars={
            "N8N_BASIC_AUTH_ACTIVE": "true",
            "N8N_BASIC_AUTH_USER": "admin",
            "N8N_BASIC_AUTH_PASSWORD": "admin",
            "GENERIC_TIMEZONE": "UTC"
        },
        volumes=["/home/node/.n8n"],
        health_check={
            "test": ["CMD-SHELL", "wget -qO- http://localhost:5678/healthz || exit 1"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3
        },
        # External config (n8n cloud)
        auth_type=AuthType.API_KEY,
        docs_url="https://docs.n8n.io",
        credential_fields=[
            CredentialField(
                key="instance_url",
                label="Instance URL",
                type="url",
                placeholder="https://your-instance.app.n8n.cloud",
                help_text="Your n8n cloud instance URL"
            ),
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="n8n_api_...",
                help_text="n8n API key for webhook triggers"
            ),
        ],
        outputs={
            "N8N_URL": "n8n instance URL",
            "N8N_API_KEY": "n8n API key"
        },
        connection_template={
            "N8N_URL": "{instance_url}",
            "N8N_API_KEY": "{api_key}"
        }
    ),

    # Turso - Edge SQLite
    "turso": ServiceDefinition(
        slug="turso",
        name="Turso",
        description="SQLite at the edge - globally distributed database with libSQL",
        category="database",
        icon="🔷",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.CONNECTION_STRING,
        docs_url="https://docs.turso.tech",
        credential_fields=[
            CredentialField(
                key="database_url",
                label="Database URL",
                type="url",
                placeholder="libsql://your-db-name.turso.io",
                help_text="Your Turso database URL"
            ),
            CredentialField(
                key="auth_token",
                label="Auth Token",
                type="password",
                placeholder="eyJhbGciOi...",
                help_text="Database authentication token"
            ),
        ],
        outputs={
            "TURSO_DATABASE_URL": "Turso database URL",
            "TURSO_AUTH_TOKEN": "Auth token"
        },
        connection_template={
            "TURSO_DATABASE_URL": "{database_url}",
            "TURSO_AUTH_TOKEN": "{auth_token}",
            "DATABASE_URL": "{database_url}?authToken={auth_token}"
        }
    ),

    # Pinecone - Vector Database
    "pinecone": ServiceDefinition(
        slug="pinecone",
        name="Pinecone",
        description="Vector database for AI applications - similarity search at scale",
        category="vector-db",
        icon="🌲",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://docs.pinecone.io",
        credential_fields=[
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                help_text="Your Pinecone API key"
            ),
            CredentialField(
                key="environment",
                label="Environment",
                type="text",
                placeholder="us-east-1-aws",
                help_text="Pinecone environment (region)"
            ),
            CredentialField(
                key="index_name",
                label="Index Name",
                type="text",
                required=False,
                placeholder="my-index",
                help_text="Default index name (optional)"
            ),
        ],
        outputs={
            "PINECONE_API_KEY": "Pinecone API key",
            "PINECONE_ENVIRONMENT": "Pinecone environment",
            "PINECONE_INDEX": "Default index name"
        },
        connection_template={
            "PINECONE_API_KEY": "{api_key}",
            "PINECONE_ENVIRONMENT": "{environment}",
            "PINECONE_INDEX": "{index_name}"
        }
    ),

    # Qdrant - Vector Database
    "qdrant": ServiceDefinition(
        slug="qdrant",
        name="Qdrant",
        description="Open-source vector database with filtering and payload support",
        category="vector-db",
        icon="🔵",
        service_type=ServiceType.HYBRID,
        # Container config (self-hosted)
        docker_image="qdrant/qdrant:latest",
        default_port=6333,
        internal_port=6333,
        environment_vars={},
        volumes=["/qdrant/storage"],
        health_check={
            "test": ["CMD-SHELL", "wget -qO- http://localhost:6333/health || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3
        },
        # External config (Qdrant Cloud)
        auth_type=AuthType.API_KEY,
        docs_url="https://qdrant.tech/documentation",
        credential_fields=[
            CredentialField(
                key="url",
                label="Cluster URL",
                type="url",
                placeholder="https://xxxxx.aws.cloud.qdrant.io:6333",
                help_text="Your Qdrant Cloud cluster URL"
            ),
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="xxxxx...",
                help_text="Qdrant Cloud API key"
            ),
        ],
        outputs={
            "QDRANT_URL": "Qdrant URL",
            "QDRANT_API_KEY": "Qdrant API key"
        },
        connection_template={
            "QDRANT_URL": "{url}",
            "QDRANT_API_KEY": "{api_key}"
        }
    ),

    # Replicate - AI Model Hosting
    "replicate": ServiceDefinition(
        slug="replicate",
        name="Replicate",
        description="Run open-source AI models in the cloud - Stable Diffusion, LLaMA, and more",
        category="ai",
        icon="🔄",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://replicate.com/docs",
        credential_fields=[
            CredentialField(
                key="api_token",
                label="API Token",
                type="password",
                placeholder="r8_...",
                help_text="Your Replicate API token"
            ),
        ],
        outputs={
            "REPLICATE_API_TOKEN": "Replicate API token"
        },
        connection_template={
            "REPLICATE_API_TOKEN": "{api_token}"
        }
    ),

    # Cloudinary - Media Management
    "cloudinary": ServiceDefinition(
        slug="cloudinary",
        name="Cloudinary",
        description="Media management platform - image and video optimization, transformation, delivery",
        category="media",
        icon="☁️",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://cloudinary.com/documentation",
        credential_fields=[
            CredentialField(
                key="cloud_name",
                label="Cloud Name",
                type="text",
                placeholder="your-cloud-name",
                help_text="Your Cloudinary cloud name"
            ),
            CredentialField(
                key="api_key",
                label="API Key",
                type="text",
                placeholder="123456789012345",
                help_text="Cloudinary API key"
            ),
            CredentialField(
                key="api_secret",
                label="API Secret",
                type="password",
                placeholder="xxxxx...",
                help_text="Cloudinary API secret"
            ),
        ],
        outputs={
            "CLOUDINARY_CLOUD_NAME": "Cloud name",
            "CLOUDINARY_API_KEY": "API key",
            "CLOUDINARY_API_SECRET": "API secret",
            "CLOUDINARY_URL": "Full Cloudinary URL"
        },
        connection_template={
            "CLOUDINARY_CLOUD_NAME": "{cloud_name}",
            "CLOUDINARY_API_KEY": "{api_key}",
            "CLOUDINARY_API_SECRET": "{api_secret}",
            "CLOUDINARY_URL": "cloudinary://{api_key}:{api_secret}@{cloud_name}",
            "NEXT_PUBLIC_CLOUDINARY_CLOUD_NAME": "{cloud_name}"
        }
    ),

    # SendGrid - Email
    "sendgrid": ServiceDefinition(
        slug="sendgrid",
        name="SendGrid",
        description="Email delivery platform - transactional and marketing emails at scale",
        category="email",
        icon="📨",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://docs.sendgrid.com",
        credential_fields=[
            CredentialField(
                key="api_key",
                label="API Key",
                type="password",
                placeholder="SG.xxxxx...",
                help_text="Your SendGrid API key"
            ),
            CredentialField(
                key="from_email",
                label="From Email",
                type="text",
                required=False,
                placeholder="noreply@yourdomain.com",
                help_text="Default sender email (optional)"
            ),
        ],
        outputs={
            "SENDGRID_API_KEY": "SendGrid API key",
            "SENDGRID_FROM_EMAIL": "Default sender email"
        },
        connection_template={
            "SENDGRID_API_KEY": "{api_key}",
            "SENDGRID_FROM_EMAIL": "{from_email}"
        }
    ),

    # Vercel KV (Upstash-based)
    "vercel-kv": ServiceDefinition(
        slug="vercel-kv",
        name="Vercel KV",
        description="Serverless Redis-compatible key-value store optimized for Vercel deployments",
        category="cache",
        icon="▲",
        service_type=ServiceType.EXTERNAL,
        auth_type=AuthType.API_KEY,
        docs_url="https://vercel.com/docs/storage/vercel-kv",
        credential_fields=[
            CredentialField(
                key="kv_url",
                label="KV URL",
                type="url",
                placeholder="redis://default:xxxxx@xxx.kv.vercel-storage.com:6379",
                help_text="Vercel KV Redis URL"
            ),
            CredentialField(
                key="kv_rest_api_url",
                label="REST API URL",
                type="url",
                placeholder="https://xxx.kv.vercel-storage.com",
                help_text="Vercel KV REST API URL"
            ),
            CredentialField(
                key="kv_rest_api_token",
                label="REST API Token",
                type="password",
                placeholder="AXxxxx...",
                help_text="Vercel KV REST API token"
            ),
        ],
        outputs={
            "KV_URL": "Redis URL",
            "KV_REST_API_URL": "REST API URL",
            "KV_REST_API_TOKEN": "REST API token"
        },
        connection_template={
            "KV_URL": "{kv_url}",
            "KV_REST_API_URL": "{kv_rest_api_url}",
            "KV_REST_API_TOKEN": "{kv_rest_api_token}"
        }
    ),

    # Grafana - Monitoring
    "grafana": ServiceDefinition(
        slug="grafana",
        name="Grafana",
        description="Open-source analytics and monitoring solution",
        category="monitoring",
        icon="📈",
        service_type=ServiceType.CONTAINER,
        docker_image="grafana/grafana:latest",
        default_port=3000,
        internal_port=3000,
        environment_vars={
            "GF_SECURITY_ADMIN_USER": "admin",
            "GF_SECURITY_ADMIN_PASSWORD": "admin",
            "GF_AUTH_ANONYMOUS_ENABLED": "true"
        },
        volumes=["/var/lib/grafana"],
        health_check={
            "test": ["CMD-SHELL", "wget -qO- http://localhost:3000/api/health || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3
        },
        outputs={
            "GRAFANA_URL": "Grafana URL"
        },
        connection_template={
            "GRAFANA_URL": "http://{container_name}:{internal_port}"
        }
    ),

    # Prometheus - Metrics
    "prometheus": ServiceDefinition(
        slug="prometheus",
        name="Prometheus",
        description="Open-source monitoring and alerting toolkit",
        category="monitoring",
        icon="🔥",
        service_type=ServiceType.CONTAINER,
        docker_image="prom/prometheus:latest",
        default_port=9090,
        internal_port=9090,
        environment_vars={},
        volumes=["/prometheus"],
        command=["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus"],
        health_check={
            "test": ["CMD-SHELL", "wget -qO- http://localhost:9090/-/healthy || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3
        },
        outputs={
            "PROMETHEUS_URL": "Prometheus URL"
        },
        connection_template={
            "PROMETHEUS_URL": "http://{container_name}:{internal_port}"
        }
    ),
}


def get_service(slug: str) -> Optional[ServiceDefinition]:
    """Get a service definition by slug"""
    return SERVICES.get(slug)


def get_services_by_category(category: str) -> List[ServiceDefinition]:
    """Get all services in a category"""
    return [s for s in SERVICES.values() if s.category == category]


def get_all_services() -> List[ServiceDefinition]:
    """Get all available services"""
    return list(SERVICES.values())


def get_container_services() -> List[ServiceDefinition]:
    """Get all container-based services (run in Docker)"""
    return [s for s in SERVICES.values() if s.service_type == ServiceType.CONTAINER]


def get_external_services() -> List[ServiceDefinition]:
    """Get all external cloud services (no container)"""
    return [s for s in SERVICES.values() if s.service_type == ServiceType.EXTERNAL]


def get_hybrid_services() -> List[ServiceDefinition]:
    """Get all hybrid services (can run either way)"""
    return [s for s in SERVICES.values() if s.service_type == ServiceType.HYBRID]


def get_services_by_type(service_type: ServiceType) -> List[ServiceDefinition]:
    """Get all services of a specific type"""
    return [s for s in SERVICES.values() if s.service_type == service_type]


def get_service_categories() -> List[str]:
    """Get all unique service categories"""
    return list(set(s.category for s in SERVICES.values()))


def get_services_requiring_credentials() -> List[ServiceDefinition]:
    """Get all services that require user credentials"""
    return [s for s in SERVICES.values() if s.credential_fields]


def service_to_dict(service: ServiceDefinition) -> Dict[str, Any]:
    """Convert a ServiceDefinition to a dictionary for API responses"""
    return {
        "slug": service.slug,
        "name": service.name,
        "description": service.description,
        "category": service.category,
        "icon": service.icon,
        "service_type": service.service_type.value,
        "docker_image": service.docker_image,
        "default_port": service.default_port,
        "internal_port": service.internal_port,
        "environment_vars": service.environment_vars,
        "volumes": service.volumes,
        "health_check": service.health_check,
        "command": service.command,
        "credential_fields": [
            {
                "key": cf.key,
                "label": cf.label,
                "type": cf.type,
                "required": cf.required,
                "placeholder": cf.placeholder,
                "help_text": cf.help_text
            }
            for cf in service.credential_fields
        ],
        "auth_type": service.auth_type.value if service.auth_type else None,
        "oauth_provider": service.oauth_provider,
        "docs_url": service.docs_url,
        "connection_template": service.connection_template,
        "outputs": service.outputs
    }
