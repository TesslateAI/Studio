import pytest

pytestmark = pytest.mark.unit

from app.services.export_resolver import build_env_from_connections, resolve_node_exports


class TestResolveNodeExports:
    def test_simple_interpolation(self):
        exports = {
            "DATABASE_URL": "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${HOST}:${PORT}/${POSTGRES_DB}"
        }
        env = {"POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "secret", "POSTGRES_DB": "app"}
        result = resolve_node_exports("postgres", exports, env, port=5432)
        assert result == {"DATABASE_URL": "postgresql://postgres:secret@postgres:5432/app"}

    def test_host_and_port_builtins(self):
        exports = {"URL": "http://${HOST}:${PORT}"}
        result = resolve_node_exports("backend", exports, {}, port=8001)
        assert result == {"URL": "http://backend:8001"}

    def test_no_interpolation_passthrough(self):
        exports = {"STATIC_KEY": "some-literal-value"}
        result = resolve_node_exports("svc", exports, {}, port=80)
        assert result == {"STATIC_KEY": "some-literal-value"}

    def test_missing_var_left_as_is(self):
        exports = {"URL": "http://${HOST}:${PORT}/${MISSING}"}
        result = resolve_node_exports("svc", exports, {}, port=80)
        assert result == {"URL": "http://svc:80/${MISSING}"}

    def test_empty_exports(self):
        result = resolve_node_exports("svc", {}, {}, port=80)
        assert result == {}

    def test_none_exports(self):
        result = resolve_node_exports("svc", None, {}, port=80)
        assert result == {}

    def test_multiple_same_var(self):
        exports = {"CONN": "${POSTGRES_USER}:${POSTGRES_USER}"}
        result = resolve_node_exports("pg", exports, {"POSTGRES_USER": "admin"}, port=5432)
        assert result == {"CONN": "admin:admin"}

    def test_env_can_override_host_and_port(self):
        """User env keys named HOST/PORT override the builtins."""
        exports = {"URL": "http://${HOST}:${PORT}"}
        result = resolve_node_exports(
            "backend", exports, {"HOST": "custom.host", "PORT": "9999"}, port=8001
        )
        assert result == {"URL": "http://custom.host:9999"}

    def test_port_none_resolves_to_empty(self):
        exports = {"URL": "http://${HOST}:${PORT}"}
        result = resolve_node_exports("svc", exports, {}, port=None)
        assert result == {"URL": "http://svc:"}

    def test_multiple_exports(self):
        exports = {
            "URL": "http://${HOST}:${PORT}",
            "INTERNAL": "${HOST}",
            "CONN_STR": "host=${HOST} port=${PORT} user=${DB_USER}",
        }
        result = resolve_node_exports("db", exports, {"DB_USER": "admin"}, port=5432)
        assert result == {
            "URL": "http://db:5432",
            "INTERNAL": "db",
            "CONN_STR": "host=db port=5432 user=admin",
        }


class TestBuildEnvFromConnections:
    def test_single_connection(self):
        nodes = {
            "backend": {
                "env": {"SECRET": "x"},
                "exports": {"API_URL": "http://${HOST}:${PORT}"},
                "port": 8001,
            },
            "postgres": {
                "env": {"POSTGRES_USER": "pg"},
                "exports": {"DB_URL": "pg://${POSTGRES_USER}@${HOST}:${PORT}"},
                "port": 5432,
            },
        }
        connections = [{"from": "backend", "to": "postgres"}]
        result = build_env_from_connections("backend", nodes, connections)
        assert result == {"DB_URL": "pg://pg@postgres:5432"}

    def test_multiple_connections_merge(self):
        nodes = {
            "backend": {"env": {}, "exports": {}, "port": 8001},
            "postgres": {"env": {}, "exports": {"DB_URL": "pg://${HOST}"}, "port": 5432},
            "redis": {"env": {}, "exports": {"REDIS_URL": "redis://${HOST}:${PORT}"}, "port": 6379},
        }
        connections = [{"from": "backend", "to": "postgres"}, {"from": "backend", "to": "redis"}]
        result = build_env_from_connections("backend", nodes, connections)
        assert result == {"DB_URL": "pg://postgres", "REDIS_URL": "redis://redis:6379"}

    def test_no_connections_empty(self):
        nodes = {"backend": {"env": {}, "exports": {}, "port": 8001}}
        result = build_env_from_connections("backend", nodes, [])
        assert result == {}

    def test_overlapping_export_keys_last_wins(self):
        """When multiple targets export the same key, last connection wins."""
        nodes = {
            "app": {"env": {}, "exports": {}, "port": 3000},
            "pg": {"env": {}, "exports": {"URL": "pg://${HOST}"}, "port": 5432},
            "redis": {"env": {}, "exports": {"URL": "redis://${HOST}"}, "port": 6379},
        }
        connections = [{"from": "app", "to": "pg"}, {"from": "app", "to": "redis"}]
        result = build_env_from_connections("app", nodes, connections)
        # redis is last, so its URL wins
        assert result == {"URL": "redis://redis"}

    def test_missing_target_node_skipped(self):
        nodes = {
            "app": {"env": {}, "exports": {}, "port": 3000},
        }
        connections = [{"from": "app", "to": "nonexistent"}]
        result = build_env_from_connections("app", nodes, connections)
        assert result == {}

    def test_reverse_connection_ignored(self):
        """Connections where node is the target (not source) are ignored."""
        nodes = {
            "backend": {"env": {}, "exports": {"API": "http://${HOST}"}, "port": 8001},
            "frontend": {"env": {}, "exports": {}, "port": 3000},
        }
        connections = [{"from": "frontend", "to": "backend"}]
        # backend is the target, not the source — should get nothing
        result = build_env_from_connections("backend", nodes, connections)
        assert result == {}

    def test_target_with_no_exports(self):
        nodes = {
            "app": {"env": {}, "exports": {}, "port": 3000},
            "worker": {"env": {"MODE": "bg"}, "exports": {}, "port": 9000},
        }
        connections = [{"from": "app", "to": "worker"}]
        result = build_env_from_connections("app", nodes, connections)
        assert result == {}
