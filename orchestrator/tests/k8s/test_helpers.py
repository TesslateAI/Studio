"""
Unit tests for Kubernetes manifest helper functions.

These functions are pure — they take parameters and return K8s client objects.
No mocking needed; we assert directly on the returned manifest structure.
"""

from uuid import uuid4

import pytest
from kubernetes import client

from app.services.orchestration.kubernetes.helpers import (
    _k8s_name,
    create_container_deployment,
    create_file_manager_deployment,
    create_ingress_manifest,
    create_network_policy_manifest,
    create_pod_affinity_spec,
    create_pvc_manifest,
    create_service_container_deployment,
    create_service_manifest,
    create_service_pvc_manifest,
    create_v2_dev_deployment,
    create_v2_project_pv,
    create_v2_project_pvc,
    create_v2_service_deployment,
    create_v2_service_pv,
    create_v2_service_pvc,
    generate_git_clone_script,
    get_standard_labels,
)

pytestmark = pytest.mark.unit


# =============================================================================
# _k8s_name
# =============================================================================


class TestK8sName:
    """Tests for DNS-1123 compliant name builder."""

    def test_normal_name(self):
        result = _k8s_name("dev-", "frontend")
        assert result == "dev-frontend"

    def test_empty_directory(self):
        result = _k8s_name("dev-", "")
        assert result == "dev-"

    def test_truncation_to_63_chars(self):
        long_dir = "a" * 100
        result = _k8s_name("dev-", long_dir)
        assert len(result) <= 63

    def test_truncation_strips_trailing_dash(self):
        # Build a name that, after truncation to 63 chars, ends with a dash.
        # "dev-" is 4 chars, so directory starting at position 4.
        # Put a dash at position 62 (index) so after truncation [:63] the last char is '-'.
        filler = "x" * 58  # 4 + 58 = 62 chars
        directory = filler + "-extra"
        result = _k8s_name("dev-", directory)
        assert len(result) <= 63
        assert not result.endswith("-")

    def test_exact_63_chars_not_truncated(self):
        directory = "x" * 59  # "dev-" (4) + 59 = 63
        result = _k8s_name("dev-", directory)
        assert len(result) == 63
        assert result == "dev-" + "x" * 59

    def test_prefix_svc(self):
        result = _k8s_name("svc-", "postgres")
        assert result == "svc-postgres"


# =============================================================================
# create_pod_affinity_spec
# =============================================================================


class TestCreatePodAffinitySpec:
    """Tests for pod affinity configuration."""

    def test_returns_v1_affinity(self):
        pid = str(uuid4())
        result = create_pod_affinity_spec(pid)
        assert isinstance(result, client.V1Affinity)

    def test_required_affinity_label(self):
        pid = str(uuid4())
        result = create_pod_affinity_spec(pid)
        terms = result.pod_affinity.required_during_scheduling_ignored_during_execution
        assert len(terms) == 1
        assert terms[0].label_selector.match_labels == {"tesslate.io/project-id": pid}

    def test_default_topology_key(self):
        pid = str(uuid4())
        result = create_pod_affinity_spec(pid)
        term = result.pod_affinity.required_during_scheduling_ignored_during_execution[0]
        assert term.topology_key == "kubernetes.io/hostname"

    def test_custom_topology_key(self):
        pid = str(uuid4())
        result = create_pod_affinity_spec(pid, topology_key="topology.kubernetes.io/zone")
        term = result.pod_affinity.required_during_scheduling_ignored_during_execution[0]
        assert term.topology_key == "topology.kubernetes.io/zone"


# =============================================================================
# get_standard_labels
# =============================================================================


class TestGetStandardLabels:
    """Tests for standard Kubernetes label generation."""

    def test_required_labels(self):
        pid, uid = str(uuid4()), str(uuid4())
        labels = get_standard_labels(pid, uid, "dev-container")
        assert labels["app.kubernetes.io/managed-by"] == "tesslate-backend"
        assert labels["tesslate.io/project-id"] == pid
        assert labels["tesslate.io/user-id"] == uid
        assert labels["tesslate.io/component"] == "dev-container"

    def test_optional_container_id(self):
        pid, uid, cid = str(uuid4()), str(uuid4()), str(uuid4())
        labels = get_standard_labels(pid, uid, "dev-container", container_id=cid)
        assert labels["tesslate.io/container-id"] == cid

    def test_optional_container_directory(self):
        pid, uid = str(uuid4()), str(uuid4())
        labels = get_standard_labels(pid, uid, "dev-container", container_directory="frontend")
        assert labels["tesslate.io/container-directory"] == "frontend"

    def test_no_optional_keys_when_omitted(self):
        pid, uid = str(uuid4()), str(uuid4())
        labels = get_standard_labels(pid, uid, "storage")
        assert "tesslate.io/container-id" not in labels
        assert "tesslate.io/container-directory" not in labels

    def test_all_params(self):
        pid, uid, cid = str(uuid4()), str(uuid4()), str(uuid4())
        labels = get_standard_labels(
            pid, uid, "dev-container", container_id=cid, container_directory="backend"
        )
        assert len(labels) == 6
        assert labels["tesslate.io/container-id"] == cid
        assert labels["tesslate.io/container-directory"] == "backend"


# =============================================================================
# create_pvc_manifest
# =============================================================================


class TestCreatePvcManifest:
    """Tests for project PVC manifest generation."""

    def test_name_is_project_storage(self):
        pvc = create_pvc_manifest("proj-ns", uuid4(), uuid4(), "gp3")
        assert pvc.metadata.name == "project-storage"

    def test_namespace(self):
        ns = "proj-test"
        pvc = create_pvc_manifest(ns, uuid4(), uuid4(), "gp3")
        assert pvc.metadata.namespace == ns

    def test_storage_class(self):
        pvc = create_pvc_manifest("ns", uuid4(), uuid4(), "tesslate-block-storage")
        assert pvc.spec.storage_class_name == "tesslate-block-storage"

    def test_default_size(self):
        pvc = create_pvc_manifest("ns", uuid4(), uuid4(), "gp3")
        assert pvc.spec.resources.requests["storage"] == "5Gi"

    def test_custom_size(self):
        pvc = create_pvc_manifest("ns", uuid4(), uuid4(), "gp3", size="10Gi")
        assert pvc.spec.resources.requests["storage"] == "10Gi"

    def test_default_access_mode(self):
        pvc = create_pvc_manifest("ns", uuid4(), uuid4(), "gp3")
        assert pvc.spec.access_modes == ["ReadWriteOnce"]

    def test_custom_access_mode(self):
        pvc = create_pvc_manifest("ns", uuid4(), uuid4(), "gp3", access_mode="ReadWriteMany")
        assert pvc.spec.access_modes == ["ReadWriteMany"]

    def test_labels_include_storage_component(self):
        pid, uid = uuid4(), uuid4()
        pvc = create_pvc_manifest("ns", pid, uid, "gp3")
        assert pvc.metadata.labels["tesslate.io/component"] == "storage"
        assert pvc.metadata.labels["tesslate.io/project-id"] == str(pid)
        assert pvc.metadata.labels["tesslate.io/user-id"] == str(uid)


# =============================================================================
# create_file_manager_deployment
# =============================================================================


class TestCreateFileManagerDeployment:
    """Tests for file-manager deployment manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "image": "tesslate-devserver:latest",
        }
        defaults.update(overrides)
        return create_file_manager_deployment(**defaults)

    def test_deployment_name(self):
        dep = self._make()
        assert dep.metadata.name == "file-manager"

    def test_image(self):
        dep = self._make(image="custom-image:v2")
        container = dep.spec.template.spec.containers[0]
        assert container.image == "custom-image:v2"

    def test_volume_mount(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        assert any(vm.mount_path == "/app" for vm in container.volume_mounts)

    def test_security_context(self):
        dep = self._make()
        sc = dep.spec.template.spec.security_context
        assert sc.run_as_non_root is True
        assert sc.run_as_user == 1000
        assert sc.fs_group == 1000

    def test_no_image_pull_secret_by_default(self):
        dep = self._make()
        assert dep.spec.template.spec.image_pull_secrets is None

    def test_image_pull_secret_added(self):
        dep = self._make(image_pull_secret="ecr-credentials")
        secrets = dep.spec.template.spec.image_pull_secrets
        assert len(secrets) == 1
        assert secrets[0].name == "ecr-credentials"

    def test_labels_contain_file_manager_app(self):
        dep = self._make()
        assert dep.metadata.labels["app"] == "file-manager"
        assert dep.metadata.labels["tesslate.io/component"] == "file-manager"

    def test_pvc_claim_name(self):
        dep = self._make()
        volumes = dep.spec.template.spec.volumes
        assert any(v.persistent_volume_claim.claim_name == "project-storage" for v in volumes)

    def test_command_is_tail(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        assert container.command == ["tail", "-f", "/dev/null"]

    def test_replicas_is_one(self):
        dep = self._make()
        assert dep.spec.replicas == 1


# =============================================================================
# create_container_deployment
# =============================================================================


class TestCreateContainerDeployment:
    """Tests for dev container deployment manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "frontend",
            "image": "tesslate-devserver:latest",
            "port": 3000,
            "startup_command": "npm run dev",
        }
        defaults.update(overrides)
        return create_container_deployment(**defaults)

    def test_deployment_name_prefix(self):
        dep = self._make(container_directory="frontend")
        assert dep.metadata.name == "dev-frontend"

    def test_tmux_command_in_args(self):
        dep = self._make(startup_command="npm run dev")
        container = dep.spec.template.spec.containers[0]
        assert "tmux new-session -d -s main" in container.args[0]
        assert "npm run dev" in container.args[0]

    def test_ports(self):
        dep = self._make(port=5173)
        container = dep.spec.template.spec.containers[0]
        assert container.ports[0].container_port == 5173
        assert container.ports[0].name == "http"

    def test_startup_probe(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        probe = container.startup_probe
        assert probe is not None
        assert "tmux has-session" in probe._exec.command[-1]

    def test_readiness_probe_http(self):
        dep = self._make(port=3000)
        container = dep.spec.template.spec.containers[0]
        probe = container.readiness_probe
        assert probe.http_get.port == 3000
        assert probe.http_get.path == "/"

    def test_liveness_probe_exec(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        probe = container.liveness_probe
        assert probe._exec is not None

    def test_affinity_enabled_by_default(self):
        pid = uuid4()
        dep = self._make(project_id=pid)
        affinity = dep.spec.template.spec.affinity
        assert affinity is not None
        term = affinity.pod_affinity.required_during_scheduling_ignored_during_execution[0]
        assert term.label_selector.match_labels["tesslate.io/project-id"] == str(pid)

    def test_affinity_disabled(self):
        dep = self._make(enable_pod_affinity=False)
        assert dep.spec.template.spec.affinity is None

    def test_image_pull_secret(self):
        dep = self._make(image_pull_secret="ecr-creds")
        secrets = dep.spec.template.spec.image_pull_secrets
        assert secrets[0].name == "ecr-creds"

    def test_extra_env(self):
        dep = self._make(extra_env={"DATABASE_URL": "postgres://localhost/db"})
        container = dep.spec.template.spec.containers[0]
        env_names = {e.name: e.value for e in container.env}
        assert env_names["DATABASE_URL"] == "postgres://localhost/db"
        # Default vars should still be present
        assert env_names["HOST"] == "0.0.0.0"
        assert env_names["PORT"] == "3000"

    def test_extra_env_cannot_override_defaults(self):
        dep = self._make(extra_env={"HOST": "127.0.0.1", "PORT": "9999"})
        container = dep.spec.template.spec.containers[0]
        env_map = {e.name: e.value for e in container.env}
        # Defaults remain unchanged
        assert env_map["HOST"] == "0.0.0.0"
        assert env_map["PORT"] == "3000"

    def test_working_directory_in_command(self):
        dep = self._make(container_directory="frontend", working_directory="client")
        container = dep.spec.template.spec.containers[0]
        assert "/app/client" in container.args[0]

    def test_working_directory_dot_maps_to_app(self):
        dep = self._make(container_directory="frontend", working_directory=".")
        container = dep.spec.template.spec.containers[0]
        assert "mkdir -p /app && cd /app" in container.args[0]

    def test_selector_uses_container_id(self):
        cid = uuid4()
        dep = self._make(container_id=cid)
        selector = dep.spec.selector.match_labels
        assert selector == {"tesslate.io/container-id": str(cid)}

    def test_security_context(self):
        dep = self._make()
        sc = dep.spec.template.spec.security_context
        assert sc.run_as_non_root is True
        assert sc.run_as_user == 1000


# =============================================================================
# create_service_manifest
# =============================================================================


class TestCreateServiceManifest:
    """Tests for ClusterIP service manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "frontend",
            "port": 3000,
        }
        defaults.update(overrides)
        return create_service_manifest(**defaults)

    def test_name_matches_dev_prefix(self):
        svc = self._make(container_directory="frontend")
        assert svc.metadata.name == "dev-frontend"

    def test_selector_uses_container_id(self):
        cid = uuid4()
        svc = self._make(container_id=cid)
        assert svc.spec.selector == {"tesslate.io/container-id": str(cid)}

    def test_port_mapping(self):
        svc = self._make(port=8080)
        port_spec = svc.spec.ports[0]
        assert port_spec.port == 8080
        assert port_spec.target_port == 8080
        assert port_spec.protocol == "TCP"

    def test_type_is_cluster_ip(self):
        svc = self._make()
        assert svc.spec.type == "ClusterIP"

    def test_labels_include_container_directory(self):
        svc = self._make(container_directory="backend")
        assert svc.metadata.labels["tesslate.io/container-directory"] == "backend"

    def test_namespace_set(self):
        svc = self._make(namespace="proj-abc")
        assert svc.metadata.namespace == "proj-abc"


# =============================================================================
# create_ingress_manifest
# =============================================================================


class TestCreateIngressManifest:
    """Tests for NGINX ingress manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "frontend",
            "project_slug": "my-app-abc123",
            "port": 3000,
            "domain": "your-domain.com",
        }
        defaults.update(overrides)
        return create_ingress_manifest(**defaults)

    def test_hostname_pattern(self):
        ing = self._make(
            project_slug="my-app-abc123",
            container_directory="frontend",
            domain="your-domain.com",
        )
        host = ing.spec.rules[0].host
        assert host == "my-app-abc123-frontend.your-domain.com"

    def test_service_backend_name(self):
        ing = self._make(container_directory="frontend", port=3000)
        backend = ing.spec.rules[0].http.paths[0].backend
        assert backend.service.name == "dev-frontend"
        assert backend.service.port.number == 3000

    def test_no_tls_by_default(self):
        ing = self._make()
        assert ing.spec.tls is None

    def test_tls_when_secret_given(self):
        ing = self._make(tls_secret="tesslate-wildcard-tls")
        tls = ing.spec.tls
        assert len(tls) == 1
        assert tls[0].secret_name == "tesslate-wildcard-tls"
        assert ing.spec.rules[0].host in tls[0].hosts

    def test_annotations_websocket_support(self):
        ing = self._make()
        annotations = ing.metadata.annotations
        assert "nginx.ingress.kubernetes.io/proxy-http-version" in annotations
        assert annotations["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "3600"
        assert annotations["nginx.ingress.kubernetes.io/proxy-send-timeout"] == "3600"

    def test_ingress_class(self):
        ing = self._make(ingress_class="nginx")
        assert ing.spec.ingress_class_name == "nginx"

    def test_custom_ingress_class(self):
        ing = self._make(ingress_class="traefik")
        assert ing.spec.ingress_class_name == "traefik"

    def test_path_type_prefix(self):
        ing = self._make()
        path = ing.spec.rules[0].http.paths[0]
        assert path.path == "/"
        assert path.path_type == "Prefix"


# =============================================================================
# create_network_policy_manifest
# =============================================================================


class TestCreateNetworkPolicyManifest:
    """Tests for project network isolation policy."""

    def _make(self, **overrides):
        defaults = {"namespace": "proj-ns", "project_id": uuid4()}
        defaults.update(overrides)
        return create_network_policy_manifest(**defaults)

    def test_name(self):
        np = self._make()
        assert np.metadata.name == "project-isolation"

    def test_policy_types(self):
        np = self._make()
        assert "Ingress" in np.spec.policy_types
        assert "Egress" in np.spec.policy_types

    def test_ingress_allows_ingress_nginx(self):
        np = self._make()
        ingress_rules = np.spec.ingress
        namespaces = []
        for rule in ingress_rules:
            for peer in rule._from:
                if peer.namespace_selector and peer.namespace_selector.match_labels:
                    namespaces.append(peer.namespace_selector.match_labels)
        assert {"kubernetes.io/metadata.name": "ingress-nginx"} in namespaces

    def test_ingress_allows_tesslate_namespace(self):
        np = self._make()
        ingress_rules = np.spec.ingress
        namespaces = []
        for rule in ingress_rules:
            for peer in rule._from:
                if peer.namespace_selector and peer.namespace_selector.match_labels:
                    namespaces.append(peer.namespace_selector.match_labels)
        assert {"kubernetes.io/metadata.name": "tesslate"} in namespaces

    def test_ingress_allows_same_namespace(self):
        np = self._make()
        ingress_rules = np.spec.ingress
        # The third ingress rule allows same-namespace communication via empty pod_selector
        has_same_ns_rule = False
        for rule in ingress_rules:
            for peer in rule._from:
                if peer.pod_selector is not None and peer.namespace_selector is None:
                    has_same_ns_rule = True
        assert has_same_ns_rule

    def test_egress_allows_dns(self):
        np = self._make()
        egress_rules = np.spec.egress
        dns_found = False
        for rule in egress_rules:
            if rule.ports:
                for p in rule.ports:
                    if p.protocol == "UDP" and p.port == 53:
                        dns_found = True
        assert dns_found

    def test_egress_allows_https(self):
        np = self._make()
        egress_rules = np.spec.egress
        https_found = False
        for rule in egress_rules:
            if rule.ports:
                for p in rule.ports:
                    if p.protocol == "TCP" and p.port == 443:
                        https_found = True
        assert https_found

    def test_egress_allows_http(self):
        np = self._make()
        egress_rules = np.spec.egress
        http_found = False
        for rule in egress_rules:
            if rule.ports:
                for p in rule.ports:
                    if p.protocol == "TCP" and p.port == 80:
                        http_found = True
        assert http_found

    def test_egress_allows_minio(self):
        np = self._make()
        egress_rules = np.spec.egress
        minio_found = False
        for rule in egress_rules:
            if rule.to:
                for peer in rule.to:
                    if (
                        peer.namespace_selector
                        and peer.namespace_selector.match_labels
                        and peer.namespace_selector.match_labels.get("kubernetes.io/metadata.name")
                        == "minio-system"
                    ):
                        minio_found = True
        assert minio_found

    def test_project_id_label(self):
        pid = uuid4()
        np = self._make(project_id=pid)
        assert np.metadata.labels["tesslate.io/project-id"] == str(pid)


# =============================================================================
# generate_git_clone_script
# =============================================================================


class TestGenerateGitCloneScript:
    """Tests for git clone shell script generation."""

    def test_contains_git_clone_command(self):
        script = generate_git_clone_script(
            "https://github.com/org/repo.git", "main", "/app/frontend"
        )
        assert "git clone" in script

    def test_branch_in_clone(self):
        script = generate_git_clone_script(
            "https://github.com/org/repo.git", "develop", "/app/frontend"
        )
        assert "--branch develop" in script

    def test_target_dir(self):
        script = generate_git_clone_script(
            "https://github.com/org/repo.git", "main", "/app/my-project"
        )
        assert 'TARGET_DIR="/app/my-project"' in script

    def test_install_deps_included_by_default(self):
        script = generate_git_clone_script(
            "https://github.com/org/repo.git", "main", "/app/frontend"
        )
        assert "npm install" in script
        assert "pip install" in script
        assert "go mod download" in script

    def test_install_deps_excluded(self):
        script = generate_git_clone_script(
            "https://github.com/org/repo.git", "main", "/app/frontend", install_deps=False
        )
        # When install_deps=False, the install commands section is omitted.
        # Check for the actual install command lines, not comments.
        assert "npm install --prefer-offline" not in script
        assert "pip install -r requirements.txt" not in script
        assert "go mod download" not in script

    def test_token_sanitized_in_log(self):
        script = generate_git_clone_script(
            "https://ghp_secret123@github.com/org/repo.git", "main", "/app/frontend"
        )
        # The safe_log_url should mask the token
        assert "ghp_secret123" not in script.split("git clone")[0]
        # But the actual clone command should still use the real URL
        assert "ghp_secret123@github.com" in script

    def test_shebang(self):
        script = generate_git_clone_script("https://github.com/org/repo.git", "main", "/app")
        assert script.startswith("#!/bin/sh")

    def test_lfs_smudge_skipped(self):
        script = generate_git_clone_script("https://github.com/org/repo.git", "main", "/app")
        assert "GIT_LFS_SKIP_SMUDGE=1" in script

    def test_bun_detection(self):
        script = generate_git_clone_script("https://github.com/org/repo.git", "main", "/app")
        assert "bun install" in script

    def test_pnpm_detection(self):
        script = generate_git_clone_script("https://github.com/org/repo.git", "main", "/app")
        assert "pnpm install" in script


# =============================================================================
# create_service_container_deployment
# =============================================================================


class TestCreateServiceContainerDeployment:
    """Tests for service container (PostgreSQL, Redis, etc.) deployment manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "postgres",
            "image": "postgres:16-alpine",
            "port": 5432,
            "environment_vars": {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "secret"},
            "volumes": ["/var/lib/postgresql/data"],
        }
        defaults.update(overrides)
        return create_service_container_deployment(**defaults)

    def test_name_svc_prefix(self):
        dep = self._make(container_directory="postgres")
        assert dep.metadata.name == "svc-postgres"

    def test_env_vars(self):
        dep = self._make(environment_vars={"REDIS_URL": "redis://localhost"})
        container = dep.spec.template.spec.containers[0]
        env_map = {e.name: e.value for e in container.env}
        assert env_map["REDIS_URL"] == "redis://localhost"

    def test_volume_mounts(self):
        dep = self._make(volumes=["/var/lib/postgresql/data"])
        container = dep.spec.template.spec.containers[0]
        assert container.volume_mounts[0].mount_path == "/var/lib/postgresql/data"
        assert container.volume_mounts[0].name == "service-data"

    def test_multiple_volume_mounts(self):
        dep = self._make(volumes=["/data", "/config"])
        container = dep.spec.template.spec.containers[0]
        names = [vm.name for vm in container.volume_mounts]
        assert names == ["service-data", "service-data-1"]

    def test_pvc_name_pattern(self):
        dep = self._make(container_directory="postgres")
        volumes = dep.spec.template.spec.volumes
        assert volumes[0].persistent_volume_claim.claim_name == "svc-postgres-data"

    def test_health_check_cmd_shell(self):
        hc = {"test": ["CMD-SHELL", "pg_isready -U postgres"]}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe is not None
        assert container.readiness_probe._exec.command == [
            "/bin/sh",
            "-c",
            "pg_isready -U postgres",
        ]

    def test_health_check_cmd(self):
        hc = {"test": ["CMD", "mysqladmin", "ping"]}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe._exec.command == ["mysqladmin", "ping"]

    def test_health_check_string(self):
        hc = {"test": "redis-cli ping"}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe._exec.command == ["/bin/sh", "-c", "redis-cli ping"]

    def test_liveness_probe_with_health_check(self):
        hc = {"test": ["CMD-SHELL", "pg_isready"]}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.liveness_probe is not None
        assert container.liveness_probe.initial_delay_seconds == 30

    def test_no_probes_without_health_check(self):
        dep = self._make(health_check=None)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe is None
        assert container.liveness_probe is None

    def test_command_override(self):
        dep = self._make(command=["redis-server", "--appendonly", "yes"])
        container = dep.spec.template.spec.containers[0]
        assert container.command == ["redis-server", "--appendonly", "yes"]

    def test_no_security_context_restrictions(self):
        dep = self._make()
        # Service containers should NOT have run_as_non_root / run_as_user
        pod_sc = dep.spec.template.spec.security_context
        assert pod_sc is None

    def test_pod_affinity_enabled(self):
        pid = uuid4()
        dep = self._make(project_id=pid, enable_pod_affinity=True)
        assert dep.spec.template.spec.affinity is not None

    def test_pod_affinity_disabled(self):
        dep = self._make(enable_pod_affinity=False)
        assert dep.spec.template.spec.affinity is None

    def test_app_label_uses_svc_prefix(self):
        dep = self._make(container_directory="redis")
        assert dep.metadata.labels["app"] == "svc-redis"


# =============================================================================
# create_service_pvc_manifest
# =============================================================================


class TestCreateServicePvcManifest:
    """Tests for service container PVC manifest."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "container_directory": "postgres",
            "storage_class": "gp3",
        }
        defaults.update(overrides)
        return create_service_pvc_manifest(**defaults)

    def test_pvc_naming(self):
        pvc = self._make(container_directory="postgres")
        assert pvc.metadata.name == "svc-postgres-data"

    def test_storage_class(self):
        pvc = self._make(storage_class="tesslate-block-storage")
        assert pvc.spec.storage_class_name == "tesslate-block-storage"

    def test_default_size(self):
        pvc = self._make()
        assert pvc.spec.resources.requests["storage"] == "1Gi"

    def test_custom_size(self):
        pvc = self._make(size="5Gi")
        assert pvc.spec.resources.requests["storage"] == "5Gi"

    def test_access_mode_rwo(self):
        pvc = self._make()
        assert pvc.spec.access_modes == ["ReadWriteOnce"]

    def test_labels_service_storage(self):
        pvc = self._make()
        assert pvc.metadata.labels["tesslate.io/component"] == "service-storage"

    def test_labels_container_directory(self):
        pvc = self._make(container_directory="redis")
        assert pvc.metadata.labels["tesslate.io/container-directory"] == "redis"


# =============================================================================
# create_v2_project_pv
# =============================================================================


class TestCreateV2ProjectPV:
    """Tests for CSI-backed project PersistentVolume."""

    def _make(self, **overrides):
        defaults = {
            "volume_id": "vol-abc123",
            "node_name": "ip-10-0-1-50.ec2.internal",
            "project_id": uuid4(),
        }
        defaults.update(overrides)
        return create_v2_project_pv(**defaults)

    def test_csi_driver(self):
        pv = self._make()
        assert pv.spec.csi.driver == "btrfs.csi.tesslate.io"

    def test_csi_volume_handle(self):
        pv = self._make(volume_id="vol-xyz")
        assert pv.spec.csi.volume_handle == "vol-xyz"

    def test_pv_name(self):
        pv = self._make(volume_id="vol-abc123")
        assert pv.metadata.name == "pv-vol-abc123"

    def test_reclaim_policy_retain(self):
        pv = self._make()
        assert pv.spec.persistent_volume_reclaim_policy == "Retain"

    def test_storage_class_empty(self):
        pv = self._make()
        assert pv.spec.storage_class_name == ""

    def test_node_affinity(self):
        pv = self._make(node_name="worker-1")
        terms = pv.spec.node_affinity.required.node_selector_terms
        assert len(terms) == 1
        expr = terms[0].match_expressions[0]
        assert expr.key == "kubernetes.io/hostname"
        assert expr.operator == "In"
        assert expr.values == ["worker-1"]

    def test_labels(self):
        pid = uuid4()
        pv = self._make(volume_id="vol-test", project_id=pid)
        assert pv.metadata.labels["tesslate.io/volume-id"] == "vol-test"
        assert pv.metadata.labels["tesslate.io/project-id"] == str(pid)

    def test_default_capacity(self):
        pv = self._make()
        assert pv.spec.capacity["storage"] == "10Gi"

    def test_custom_capacity(self):
        pv = self._make(size="20Gi")
        assert pv.spec.capacity["storage"] == "20Gi"

    def test_access_modes(self):
        pv = self._make()
        assert pv.spec.access_modes == ["ReadWriteOnce"]


# =============================================================================
# create_v2_project_pvc
# =============================================================================


class TestCreateV2ProjectPVC:
    """Tests for CSI-backed project PVC that binds to a static PV."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "volume_id": "vol-abc123",
            "project_id": uuid4(),
            "user_id": uuid4(),
        }
        defaults.update(overrides)
        return create_v2_project_pvc(**defaults)

    def test_name_is_project_source(self):
        pvc = self._make()
        assert pvc.metadata.name == "project-source"

    def test_storage_class_name_empty(self):
        pvc = self._make()
        assert pvc.spec.storage_class_name == ""

    def test_volume_name_references_pv(self):
        pvc = self._make(volume_id="vol-xyz")
        assert pvc.spec.volume_name == "pv-vol-xyz"

    def test_namespace(self):
        pvc = self._make(namespace="proj-test-123")
        assert pvc.metadata.namespace == "proj-test-123"

    def test_labels(self):
        pid, uid = uuid4(), uuid4()
        pvc = self._make(project_id=pid, user_id=uid)
        assert pvc.metadata.labels["tesslate.io/project-id"] == str(pid)
        assert pvc.metadata.labels["tesslate.io/user-id"] == str(uid)
        assert pvc.metadata.labels["tesslate.io/component"] == "storage"

    def test_default_size(self):
        pvc = self._make()
        assert pvc.spec.resources.requests["storage"] == "10Gi"

    def test_access_modes(self):
        pvc = self._make()
        assert pvc.spec.access_modes == ["ReadWriteOnce"]


# =============================================================================
# create_v2_service_pv
# =============================================================================


class TestCreateV2ServicePV:
    """Tests for CSI-backed service PV with service-dir label."""

    def _make(self, **overrides):
        defaults = {
            "service_volume_id": "svc-vol-pg",
            "node_name": "worker-1",
            "project_id": uuid4(),
            "service_dir": "postgres",
        }
        defaults.update(overrides)
        return create_v2_service_pv(**defaults)

    def test_csi_driver(self):
        pv = self._make()
        assert pv.spec.csi.driver == "btrfs.csi.tesslate.io"

    def test_pv_name(self):
        pv = self._make(service_volume_id="svc-vol-pg")
        assert pv.metadata.name == "pv-svc-vol-pg"

    def test_labels_include_service_dir(self):
        pv = self._make(service_dir="postgres")
        assert pv.metadata.labels["tesslate.io/service-dir"] == "postgres"

    def test_labels_include_volume_id(self):
        pv = self._make(service_volume_id="vol-redis")
        assert pv.metadata.labels["tesslate.io/volume-id"] == "vol-redis"

    def test_labels_include_project_id(self):
        pid = uuid4()
        pv = self._make(project_id=pid)
        assert pv.metadata.labels["tesslate.io/project-id"] == str(pid)

    def test_node_affinity(self):
        pv = self._make(node_name="worker-2")
        terms = pv.spec.node_affinity.required.node_selector_terms
        expr = terms[0].match_expressions[0]
        assert expr.values == ["worker-2"]

    def test_reclaim_policy(self):
        pv = self._make()
        assert pv.spec.persistent_volume_reclaim_policy == "Retain"

    def test_storage_class_empty(self):
        pv = self._make()
        assert pv.spec.storage_class_name == ""


# =============================================================================
# create_v2_service_pvc
# =============================================================================


class TestCreateV2ServicePVC:
    """Tests for CSI-backed service PVC naming and binding."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "service_volume_id": "svc-vol-pg",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "service_dir": "postgres",
        }
        defaults.update(overrides)
        return create_v2_service_pvc(**defaults)

    def test_pvc_name_pattern(self):
        pvc = self._make(service_dir="postgres")
        assert pvc.metadata.name == "svc-postgres-data"

    def test_volume_name_references_pv(self):
        pvc = self._make(service_volume_id="svc-vol-pg")
        assert pvc.spec.volume_name == "pv-svc-vol-pg"

    def test_storage_class_empty(self):
        pvc = self._make()
        assert pvc.spec.storage_class_name == ""

    def test_labels(self):
        pid, uid = uuid4(), uuid4()
        pvc = self._make(project_id=pid, user_id=uid)
        assert pvc.metadata.labels["tesslate.io/project-id"] == str(pid)
        assert pvc.metadata.labels["tesslate.io/user-id"] == str(uid)

    def test_access_modes(self):
        pvc = self._make()
        assert pvc.spec.access_modes == ["ReadWriteOnce"]

    def test_default_size(self):
        pvc = self._make()
        assert pvc.spec.resources.requests["storage"] == "10Gi"


# =============================================================================
# create_v2_dev_deployment
# =============================================================================


class TestCreateV2DevDeployment:
    """Tests for v2 CSI-backed dev container deployment."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "frontend",
            "image": "tesslate-devserver:latest",
            "port": 3000,
            "startup_command": "npm run dev",
        }
        defaults.update(overrides)
        return create_v2_dev_deployment(**defaults)

    def test_tier_2_label(self):
        dep = self._make()
        assert dep.metadata.labels["tesslate.io/tier"] == "2"

    def test_pvc_volume_name(self):
        dep = self._make()
        volumes = dep.spec.template.spec.volumes
        assert volumes[0].name == "project-source"
        assert volumes[0].persistent_volume_claim.claim_name == "project-source"

    def test_custom_pvc_name(self):
        dep = self._make(pvc_name="custom-pvc")
        volumes = dep.spec.template.spec.volumes
        assert volumes[0].persistent_volume_claim.claim_name == "custom-pvc"

    def test_tmux_command_pattern(self):
        dep = self._make(startup_command="npm run dev")
        container = dep.spec.template.spec.containers[0]
        assert "tmux new-session -d -s main" in container.args[0]
        assert "npm run dev" in container.args[0]
        assert "tail -f /dev/null" in container.args[0]

    def test_volume_mount_path(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        vm = container.volume_mounts[0]
        assert vm.mount_path == "/app"
        assert vm.name == "project-source"

    def test_deployment_name(self):
        dep = self._make(container_directory="frontend")
        assert dep.metadata.name == "dev-frontend"

    def test_security_context(self):
        dep = self._make()
        sc = dep.spec.template.spec.security_context
        assert sc.run_as_non_root is True
        assert sc.run_as_user == 1000
        assert sc.fs_group == 1000

    def test_image_pull_secret(self):
        dep = self._make(image_pull_secret="ecr-credentials")
        secrets = dep.spec.template.spec.image_pull_secrets
        assert secrets[0].name == "ecr-credentials"

    def test_no_image_pull_secret_by_default(self):
        dep = self._make()
        assert dep.spec.template.spec.image_pull_secrets is None

    def test_extra_env(self):
        dep = self._make(extra_env={"MY_VAR": "hello"})
        container = dep.spec.template.spec.containers[0]
        env_map = {e.name: e.value for e in container.env}
        assert env_map["MY_VAR"] == "hello"
        assert env_map["HOST"] == "0.0.0.0"

    def test_extra_env_cannot_override_defaults(self):
        dep = self._make(extra_env={"HOST": "127.0.0.1"})
        container = dep.spec.template.spec.containers[0]
        env_map = {e.name: e.value for e in container.env}
        assert env_map["HOST"] == "0.0.0.0"

    def test_automount_service_account_false(self):
        dep = self._make()
        assert dep.spec.template.spec.automount_service_account_token is False

    def test_startup_probe(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        assert container.startup_probe is not None
        assert "tmux has-session" in container.startup_probe._exec.command[-1]

    def test_readiness_probe(self):
        dep = self._make(port=5173)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe.http_get.port == 5173

    def test_liveness_probe(self):
        dep = self._make()
        container = dep.spec.template.spec.containers[0]
        assert container.liveness_probe is not None

    def test_working_directory_fallback_to_container_directory(self):
        dep = self._make(container_directory="frontend", working_directory="")
        container = dep.spec.template.spec.containers[0]
        assert "/app/frontend" in container.args[0]

    def test_working_directory_dot(self):
        dep = self._make(container_directory="frontend", working_directory=".")
        container = dep.spec.template.spec.containers[0]
        assert "mkdir -p /app && cd /app" in container.args[0]

    def test_selector_labels(self):
        cid = uuid4()
        dep = self._make(container_id=cid)
        assert dep.spec.selector.match_labels == {"tesslate.io/container-id": str(cid)}

    def test_no_pod_affinity(self):
        """v2 relies on PV node affinity, no explicit pod affinity."""
        dep = self._make()
        assert dep.spec.template.spec.affinity is None


# =============================================================================
# create_v2_service_deployment
# =============================================================================


class TestCreateV2ServiceDeployment:
    """Tests for v2 CSI-backed service container deployment."""

    def _make(self, **overrides):
        defaults = {
            "namespace": "proj-ns",
            "project_id": uuid4(),
            "user_id": uuid4(),
            "container_id": uuid4(),
            "container_directory": "postgres",
            "image": "postgres:16-alpine",
            "port": 5432,
            "environment_vars": {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "secret"},
            "volumes": ["/var/lib/postgresql/data"],
            "service_pvc_name": "svc-postgres-data",
        }
        defaults.update(overrides)
        return create_v2_service_deployment(**defaults)

    def test_env_vars(self):
        dep = self._make(environment_vars={"PG_USER": "test"})
        container = dep.spec.template.spec.containers[0]
        env_map = {e.name: e.value for e in container.env}
        assert env_map["PG_USER"] == "test"

    def test_volume_mounts(self):
        dep = self._make(volumes=["/var/lib/postgresql/data"])
        container = dep.spec.template.spec.containers[0]
        assert container.volume_mounts[0].mount_path == "/var/lib/postgresql/data"

    def test_volume_specs_reference_pvc(self):
        dep = self._make(service_pvc_name="svc-postgres-data")
        volumes = dep.spec.template.spec.volumes
        assert volumes[0].persistent_volume_claim.claim_name == "svc-postgres-data"

    def test_health_check_conversion(self):
        hc = {"test": ["CMD-SHELL", "pg_isready -U postgres"]}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe is not None
        assert container.liveness_probe is not None
        assert container.readiness_probe._exec.command == [
            "/bin/sh",
            "-c",
            "pg_isready -U postgres",
        ]

    def test_no_security_context_restrictions(self):
        dep = self._make()
        pod_sc = dep.spec.template.spec.security_context
        assert pod_sc is None

    def test_tier_2_label(self):
        dep = self._make()
        assert dep.metadata.labels["tesslate.io/tier"] == "2"

    def test_deployment_name_svc_prefix(self):
        dep = self._make(container_directory="redis")
        assert dep.metadata.name == "svc-redis"

    def test_app_label(self):
        dep = self._make(container_directory="postgres")
        assert dep.metadata.labels["app"] == "svc-postgres"

    def test_command_override(self):
        dep = self._make(command=["redis-server"])
        container = dep.spec.template.spec.containers[0]
        assert container.command == ["redis-server"]

    def test_no_command_by_default(self):
        dep = self._make(command=None)
        container = dep.spec.template.spec.containers[0]
        assert container.command is None

    def test_automount_service_account_false(self):
        dep = self._make()
        assert dep.spec.template.spec.automount_service_account_token is False

    def test_no_pod_affinity(self):
        """v2 service uses PV node affinity, no pod affinity."""
        dep = self._make()
        assert dep.spec.template.spec.affinity is None

    def test_multiple_volumes(self):
        dep = self._make(
            volumes=["/data", "/config"],
            service_pvc_name="svc-mydb-data",
        )
        container = dep.spec.template.spec.containers[0]
        assert len(container.volume_mounts) == 2
        assert container.volume_mounts[0].name == "service-data"
        assert container.volume_mounts[1].name == "service-data-1"
        # All volumes reference the same PVC
        volumes = dep.spec.template.spec.volumes
        assert all(v.persistent_volume_claim.claim_name == "svc-mydb-data" for v in volumes)

    def test_no_volumes_when_empty_list(self):
        dep = self._make(volumes=[], service_pvc_name=None)
        container = dep.spec.template.spec.containers[0]
        assert container.volume_mounts is None
        assert dep.spec.template.spec.volumes is None

    def test_health_check_plain_string(self):
        hc = {"test": "redis-cli ping"}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe._exec.command == ["/bin/sh", "-c", "redis-cli ping"]

    def test_health_check_cmd_list(self):
        hc = {"test": ["CMD", "mysqladmin", "ping", "-h", "localhost"]}
        dep = self._make(health_check=hc)
        container = dep.spec.template.spec.containers[0]
        assert container.readiness_probe._exec.command == ["mysqladmin", "ping", "-h", "localhost"]

    def test_selector_labels(self):
        cid = uuid4()
        dep = self._make(container_id=cid)
        assert dep.spec.selector.match_labels == {"tesslate.io/container-id": str(cid)}
