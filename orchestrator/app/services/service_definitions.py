"""
Service Definitions

Pre-configured containerized services that users can drag into their projects.
These are different from bases - they're ready-to-use Docker images for databases,
message queues, caches, proxies, etc.

Each service has:
- Docker image
- Default environment variables
- Exposed ports
- Volume configuration (for data persistence)
- Health checks
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ServiceDefinition:
    """Defines a draggable service"""
    slug: str
    name: str
    description: str
    category: str  # database, cache, queue, proxy, search, storage
    icon: str  # Emoji icon for the service
    docker_image: str
    default_port: int
    internal_port: int
    environment_vars: Dict[str, str]
    volumes: List[str]  # Volume mount paths
    health_check: Optional[Dict[str, Any]] = None
    command: Optional[List[str]] = None


# Service catalog
SERVICES: Dict[str, ServiceDefinition] = {
    # Databases
    "postgres": ServiceDefinition(
        slug="postgres",
        name="PostgreSQL",
        description="PostgreSQL 16 - Powerful open-source relational database",
        category="database",
        icon="🐘",
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
        }
    ),

    "mysql": ServiceDefinition(
        slug="mysql",
        name="MySQL",
        description="MySQL 8 - World's most popular open-source database",
        category="database",
        icon="🐬",
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
        }
    ),

    "mongodb": ServiceDefinition(
        slug="mongodb",
        name="MongoDB",
        description="MongoDB 7 - Document-oriented NoSQL database",
        category="database",
        icon="🍃",
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
        }
    ),

    # Cache
    "redis": ServiceDefinition(
        slug="redis",
        name="Redis",
        description="Redis 7 - In-memory data structure store",
        category="cache",
        icon="🔴",
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
        }
    ),

    # Message Queues
    "rabbitmq": ServiceDefinition(
        slug="rabbitmq",
        name="RabbitMQ",
        description="RabbitMQ - Message broker with management UI",
        category="queue",
        icon="🐰",
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
        }
    ),

    # Search
    "elasticsearch": ServiceDefinition(
        slug="elasticsearch",
        name="Elasticsearch",
        description="Elasticsearch 8 - Distributed search and analytics engine",
        category="search",
        icon="🔍",
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
        }
    ),

    # Storage
    "minio": ServiceDefinition(
        slug="minio",
        name="MinIO",
        description="MinIO - S3-compatible object storage",
        category="storage",
        icon="📦",
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
        }
    ),

    # Proxy/Web Server
    "nginx": ServiceDefinition(
        slug="nginx",
        name="Nginx",
        description="Nginx - High-performance web server and reverse proxy",
        category="proxy",
        icon="🌐",
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


def get_service_categories() -> List[str]:
    """Get all unique service categories"""
    return list(set(s.category for s in SERVICES.values()))
