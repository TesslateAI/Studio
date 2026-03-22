import json
import pytest
from app.services.base_config_parser import (
    parse_tesslate_config,
    write_tesslate_config,
    read_tesslate_config,
    serialize_config_to_json,
    TesslateProjectConfig,
    AppConfig,
    InfraConfig,
    ConnectionConfig,
    DeploymentConfig,
    PreviewConfig,
)


class TestParseNewConfigFields:
    def test_old_config_backwards_compatible(self):
        """Old configs with just apps/infrastructure/primaryApp still parse."""
        config = parse_tesslate_config('{"apps": {"fe": {"start": "npm run dev"}}, "infrastructure": {}, "primaryApp": "fe"}')
        assert config.apps["fe"].start == "npm run dev"
        assert config.connections == []
        assert config.deployments == {}
        assert config.previews == {}

    def test_exports_on_apps(self):
        config = parse_tesslate_config('{"apps": {"api": {"start": "npm start", "exports": {"API_URL": "http://${HOST}:${PORT}"}}}, "primaryApp": "api"}')
        assert config.apps["api"].exports == {"API_URL": "http://${HOST}:${PORT}"}

    def test_exports_on_infrastructure(self):
        config = parse_tesslate_config('{"apps": {}, "infrastructure": {"pg": {"image": "postgres:16", "port": 5432, "env": {"PG_USER": "x"}, "exports": {"DB_URL": "pg://${HOST}"}}}, "primaryApp": ""}')
        assert config.infrastructure["pg"].exports == {"DB_URL": "pg://${HOST}"}
        assert config.infrastructure["pg"].env == {"PG_USER": "x"}

    def test_connections_parsed(self):
        raw = '{"apps": {"a": {"start": "npm start"}}, "infrastructure": {"pg": {"image": "pg", "port": 5432}}, "connections": [{"from": "a", "to": "pg"}], "primaryApp": "a"}'
        config = parse_tesslate_config(raw)
        assert len(config.connections) == 1
        assert config.connections[0].from_node == "a"
        assert config.connections[0].to_node == "pg"

    def test_deployments_parsed(self):
        raw = '{"apps": {"fe": {"start": "npm start"}}, "deployments": {"prod": {"provider": "vercel", "targets": ["fe"], "env": {"NODE_ENV": "production"}, "x": 100, "y": -50}}, "primaryApp": "fe"}'
        config = parse_tesslate_config(raw)
        assert "prod" in config.deployments
        assert config.deployments["prod"].provider == "vercel"
        assert config.deployments["prod"].targets == ["fe"]
        assert config.deployments["prod"].env == {"NODE_ENV": "production"}

    def test_previews_parsed(self):
        raw = '{"apps": {"fe": {"start": "npm start"}}, "previews": {"main": {"target": "fe", "x": -100, "y": 50}}, "primaryApp": "fe"}'
        config = parse_tesslate_config(raw)
        assert "main" in config.previews
        assert config.previews["main"].target == "fe"

    def test_external_infrastructure(self):
        raw = '{"apps": {}, "infrastructure": {"sb": {"type": "external", "provider": "supabase", "endpoint": "https://x.supabase.co", "exports": {"SUPABASE_URL": "https://x.supabase.co"}}}, "primaryApp": ""}'
        config = parse_tesslate_config(raw)
        assert config.infrastructure["sb"].infra_type == "external"
        assert config.infrastructure["sb"].endpoint == "https://x.supabase.co"

    def test_empty_connections_list(self):
        """Empty connections list should parse to empty, not be skipped."""
        raw = '{"apps": {"fe": {"start": "npm start"}}, "connections": [], "primaryApp": "fe"}'
        config = parse_tesslate_config(raw)
        assert config.connections == []

    def test_empty_deployments_dict(self):
        raw = '{"apps": {"fe": {"start": "npm start"}}, "deployments": {}, "primaryApp": "fe"}'
        config = parse_tesslate_config(raw)
        assert config.deployments == {}

    def test_empty_previews_dict(self):
        raw = '{"apps": {"fe": {"start": "npm start"}}, "previews": {}, "primaryApp": "fe"}'
        config = parse_tesslate_config(raw)
        assert config.previews == {}

    def test_multiple_connections(self):
        raw = json.dumps({
            "apps": {"api": {"start": "npm start"}},
            "infrastructure": {
                "pg": {"image": "pg", "port": 5432},
                "redis": {"image": "redis", "port": 6379},
            },
            "connections": [
                {"from": "api", "to": "pg"},
                {"from": "api", "to": "redis"},
            ],
            "primaryApp": "api",
        })
        config = parse_tesslate_config(raw)
        assert len(config.connections) == 2
        targets = {c.to_node for c in config.connections}
        assert targets == {"pg", "redis"}

    def test_app_without_exports_defaults_empty(self):
        config = parse_tesslate_config('{"apps": {"fe": {"start": "npm start"}}, "primaryApp": "fe"}')
        assert config.apps["fe"].exports == {}

    def test_deployment_with_no_env(self):
        raw = json.dumps({
            "apps": {"fe": {"start": "npm start"}},
            "deployments": {"prod": {"provider": "netlify", "targets": ["fe"]}},
            "primaryApp": "fe",
        })
        config = parse_tesslate_config(raw)
        assert config.deployments["prod"].env == {}


class TestWriteNewConfigFields:
    def test_roundtrip_full_config(self):
        import tempfile

        config = TesslateProjectConfig()
        config.apps["api"] = AppConfig(directory="server", port=8001, start="npm start", env={"KEY": "val"}, exports={"API_URL": "http://${HOST}:${PORT}"}, x=100, y=200)
        config.infrastructure["pg"] = InfraConfig(image="postgres:16", port=5432, env={"PG_USER": "x"}, exports={"DB": "pg://${HOST}"}, x=300, y=400)
        config.connections = [ConnectionConfig(from_node="api", to_node="pg")]
        config.deployments["prod"] = DeploymentConfig(provider="vercel", targets=["api"], env={"NODE_ENV": "production"}, x=500, y=-100)
        config.previews["p1"] = PreviewConfig(target="api", x=-100, y=50)
        config.primaryApp = "api"

        with tempfile.TemporaryDirectory() as tmpdir:
            write_tesslate_config(tmpdir, config)
            loaded = read_tesslate_config(tmpdir)
            assert loaded is not None
            assert loaded.apps["api"].exports == {"API_URL": "http://${HOST}:${PORT}"}
            assert loaded.infrastructure["pg"].env == {"PG_USER": "x"}
            assert len(loaded.connections) == 1
            assert loaded.connections[0].from_node == "api"
            assert loaded.deployments["prod"].provider == "vercel"
            assert loaded.previews["p1"].target == "api"

    def test_serialize_config_to_json(self):
        config = TesslateProjectConfig()
        config.apps["fe"] = AppConfig(start="npm start", exports={"URL": "http://${HOST}"})
        config.primaryApp = "fe"

        json_str = serialize_config_to_json(config)
        data = json.loads(json_str)
        assert data["apps"]["fe"]["exports"] == {"URL": "http://${HOST}"}
        assert data["primaryApp"] == "fe"

    def test_empty_sections_omitted(self):
        config = TesslateProjectConfig()
        config.apps["fe"] = AppConfig(start="npm start")
        config.primaryApp = "fe"

        json_str = serialize_config_to_json(config)
        data = json.loads(json_str)
        assert "connections" not in data
        assert "deployments" not in data
        assert "previews" not in data

    def test_connections_serialized_with_from_to_keys(self):
        """Connections serialize using 'from'/'to' keys, not 'from_node'/'to_node'."""
        config = TesslateProjectConfig()
        config.apps["api"] = AppConfig(start="npm start")
        config.infrastructure["pg"] = InfraConfig(image="pg", port=5432)
        config.connections = [ConnectionConfig(from_node="api", to_node="pg")]
        config.primaryApp = "api"

        json_str = serialize_config_to_json(config)
        data = json.loads(json_str)
        assert len(data["connections"]) == 1
        conn = data["connections"][0]
        assert "from" in conn
        assert "to" in conn
        assert "from_node" not in conn
        assert "to_node" not in conn
        assert conn["from"] == "api"
        assert conn["to"] == "pg"

    def test_roundtrip_empty_collections(self):
        """Config with explicitly empty connections/deployments/previews round-trips correctly."""
        import tempfile

        config = TesslateProjectConfig()
        config.apps["fe"] = AppConfig(start="npm start")
        config.connections = []
        config.deployments = {}
        config.previews = {}
        config.primaryApp = "fe"

        with tempfile.TemporaryDirectory() as tmpdir:
            write_tesslate_config(tmpdir, config)
            loaded = read_tesslate_config(tmpdir)
            assert loaded is not None
            assert loaded.connections == []
            assert loaded.deployments == {}
            assert loaded.previews == {}

    def test_roundtrip_external_infra(self):
        import tempfile

        config = TesslateProjectConfig()
        config.infrastructure["supabase"] = InfraConfig(
            infra_type="external",
            provider="supabase",
            endpoint="https://x.supabase.co",
            exports={"URL": "https://x.supabase.co"},
        )
        config.primaryApp = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            write_tesslate_config(tmpdir, config)
            loaded = read_tesslate_config(tmpdir)
            assert loaded is not None
            assert loaded.infrastructure["supabase"].infra_type == "external"
            assert loaded.infrastructure["supabase"].endpoint == "https://x.supabase.co"


class TestConnectionConfigSchemaAlias:
    """Verify Pydantic schema alias behavior for ConnectionConfigSchema."""

    def test_deserialize_from_json_keys(self):
        from app.schemas import ConnectionConfigSchema

        schema = ConnectionConfigSchema.model_validate({"from": "api", "to": "pg"})
        assert schema.from_node == "api"
        assert schema.to_node == "pg"

    def test_deserialize_from_field_names(self):
        from app.schemas import ConnectionConfigSchema

        schema = ConnectionConfigSchema.model_validate({"from_node": "api", "to_node": "pg"})
        assert schema.from_node == "api"
        assert schema.to_node == "pg"

    def test_serialize_uses_alias_keys(self):
        """Serialization must use 'from'/'to', not 'from_node'/'to_node'."""
        from app.schemas import ConnectionConfigSchema

        schema = ConnectionConfigSchema(from_node="api", to_node="pg")
        dumped = schema.model_dump(by_alias=True)
        assert "from" in dumped
        assert "to" in dumped
        assert "from_node" not in dumped
        assert "to_node" not in dumped

    def test_serialize_by_alias_default(self):
        """With serialize_by_alias in model_config, model_dump() uses aliases by default."""
        from app.schemas import ConnectionConfigSchema

        schema = ConnectionConfigSchema(from_node="api", to_node="pg")
        dumped = schema.model_dump()
        assert "from" in dumped
        assert "to" in dumped
