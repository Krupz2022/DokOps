"""A config change must land on the object that OWNS the value.

Regression: asked to change a setting, the agent called patch_deployment_env,
which sets `value_from = None` — so a var sourced from a configMapKeyRef was
silently DETACHED from its ConfigMap rather than changed. The ConfigMap kept the
stale value for every other consumer, and the next helm sync reverted the
literal. Nothing looked first: ConfigMaps are in the topology graph but
get_cluster_overview never renders them.

Two layers, tested separately because they must work independently:
  build_config_sources  — hands the agent the owner map before it picks a tool
  _env_var_owner        — refuses the destructive patch when it picks wrong anyway
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.presweep import _format_env, build_config_sources
from app.tools.k8s_tools import _env_var_owner


# ── fixtures ─────────────────────────────────────────────────────────────────

def _env(name, *, value=None, cm=None, secret=None, key=None, field=None):
    """A V1EnvVar shaped like kubernetes_asyncio returns it."""
    value_from = None
    if cm:
        value_from = SimpleNamespace(
            config_map_key_ref=SimpleNamespace(name=cm, key=key),
            secret_key_ref=None, field_ref=None, resource_field_ref=None)
    elif secret:
        value_from = SimpleNamespace(
            config_map_key_ref=None,
            secret_key_ref=SimpleNamespace(name=secret, key=key),
            field_ref=None, resource_field_ref=None)
    elif field:
        value_from = SimpleNamespace(
            config_map_key_ref=None, secret_key_ref=None,
            field_ref=SimpleNamespace(field_path=field), resource_field_ref=None)
    return SimpleNamespace(name=name, value=value, value_from=value_from)


def _container(env=None, env_from=None):
    return SimpleNamespace(name="app", env=env or [], env_from=env_from or [])


def _core_with(configmaps=None, secrets=None):
    core = SimpleNamespace()
    core.read_namespaced_config_map = AsyncMock(side_effect=lambda n, ns: SimpleNamespace(
        data=(configmaps or {})[n]))
    core.read_namespaced_secret = AsyncMock(side_effect=lambda n, ns: SimpleNamespace(
        data=(secrets or {})[n]))
    return core


# ── layer 2: the patch must refuse when it would detach ──────────────────────

@pytest.mark.asyncio
async def test_configmapkeyref_patch_is_refused():
    """THE regression. Patching here would null out value_from."""
    container = _container([_env("LOG_LEVEL", cm="checkout-config", key="log_level")])
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=None):
        err = await _env_var_owner(container, "LOG_LEVEL", "payments")

    assert err is not None
    assert "configmap/checkout-config" in err
    assert "log_level" in err
    assert "update_configmap" in err  # names the tool that WOULD work


@pytest.mark.asyncio
async def test_secretkeyref_patch_is_refused_and_warns_about_plaintext():
    container = _container([_env("DB_PASSWORD", secret="checkout-db", key="password")])
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=None):
        err = await _env_var_owner(container, "DB_PASSWORD", "payments")

    assert "secret/checkout-db" in err
    assert "PLAINTEXT" in err


@pytest.mark.asyncio
async def test_downward_api_patch_is_refused():
    container = _container([_env("POD_IP", field="status.podIP")])
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=None):
        err = await _env_var_owner(container, "POD_IP", "payments")

    assert "status.podIP" in err


@pytest.mark.asyncio
async def test_literal_in_the_deployment_is_allowed():
    """The deployment really does own this one — the tool is correct here."""
    container = _container([_env("PORT", value="8080")])
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=None):
        assert await _env_var_owner(container, "PORT", "payments") is None


@pytest.mark.asyncio
async def test_brand_new_var_with_no_refs_is_allowed():
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=None):
        assert await _env_var_owner(_container(), "NEW_FLAG", "payments") is None


@pytest.mark.asyncio
async def test_envfrom_shadowing_is_refused():
    """Same fault one step removed: the var has no entry of its own, so the tool
    APPENDS a literal — which shadows the ConfigMap that still holds the old value."""
    container = _container(env_from=[SimpleNamespace(
        prefix=None,
        config_map_ref=SimpleNamespace(name="checkout-flags"),
        secret_ref=None)])
    core = _core_with(configmaps={"checkout-flags": {"FEATURE_X": "off"}})
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=core):
        err = await _env_var_owner(container, "FEATURE_X", "payments")

    assert "configmap/checkout-flags" in err
    assert "shadow" in err


@pytest.mark.asyncio
async def test_envfrom_prefix_is_stripped_before_the_key_lookup():
    container = _container(env_from=[SimpleNamespace(
        prefix="APP_",
        config_map_ref=SimpleNamespace(name="checkout-flags"),
        secret_ref=None)])
    core = _core_with(configmaps={"checkout-flags": {"FEATURE_X": "off"}})
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=core):
        err = await _env_var_owner(container, "APP_FEATURE_X", "payments")

    assert err is not None and "FEATURE_X" in err


@pytest.mark.asyncio
async def test_envfrom_configmap_without_the_key_does_not_block():
    """An envFrom ref is not ownership on its own — only the key being in it is."""
    container = _container(env_from=[SimpleNamespace(
        prefix=None,
        config_map_ref=SimpleNamespace(name="checkout-flags"),
        secret_ref=None)])
    core = _core_with(configmaps={"checkout-flags": {"SOMETHING_ELSE": "1"}})
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=core):
        assert await _env_var_owner(container, "FEATURE_X", "payments") is None


@pytest.mark.asyncio
async def test_unreadable_configmap_does_not_block_the_patch():
    """Fail open: an RBAC-denied read is not proof the ConfigMap owns the var."""
    container = _container(env_from=[SimpleNamespace(
        prefix=None,
        config_map_ref=SimpleNamespace(name="denied"),
        secret_ref=None)])
    core = SimpleNamespace(read_namespaced_config_map=AsyncMock(side_effect=Exception("403")))
    with patch("app.tools.k8s_tools.k8s_service._get_api", return_value=core):
        assert await _env_var_owner(container, "FEATURE_X", "payments") is None


# ── layer 1: the owner map handed over before the agent chooses ──────────────

def test_secretish_literal_values_are_redacted():
    """CLAUDE.md §3a — a password hardcoded in a pod spec must not reach context."""
    assert "<redacted>" in _format_env(
        {"name": "DB_PASSWORD", "source": "literal", "value": "hunter2"})
    assert "hunter2" not in _format_env(
        {"name": "DB_PASSWORD", "source": "literal", "value": "hunter2"})
    assert "8080" in _format_env({"name": "PORT", "source": "literal", "value": "8080"})


def test_owner_arrow_distinguishes_owned_from_local():
    owned = _format_env({"name": "LOG_LEVEL", "source": "configMapKeyRef",
                         "configmap_name": "checkout-config", "key": "log_level"})
    local = _format_env({"name": "PORT", "source": "literal", "value": "8080"})
    assert "<-" in owned and "configmap/checkout-config" in owned
    assert "patch it HERE" in local


def _deployment_lister(*names):
    apps = SimpleNamespace()
    apps.list_namespaced_deployment = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name=n)) for n in names]))
    return apps


_WORKLOAD_CONFIG = {
    "success": True,
    "data": {
        "deployment": "checkout-api", "namespace": "payments",
        "volume_configmaps": [{"volume_name": "files", "configmap_name": "checkout-files"}],
        "volume_secrets": [],
        "containers": [{
            "container_name": "checkout",
            "env_vars": [
                {"name": "LOG_LEVEL", "source": "configMapKeyRef",
                 "configmap_name": "checkout-config", "key": "log_level"},
                {"name": "PORT", "source": "literal", "value": "8080"},
            ],
            "env_from_configmaps": [{"configmap_name": "checkout-flags", "prefix": None}],
            "env_from_secrets": [],
            "volume_mounts": [{"name": "files", "mount_path": "/etc/app", "sub_path": None}],
        }],
    },
    "error": None, "source": "k8s_client",
}


@pytest.mark.asyncio
async def test_config_sources_names_the_owner_of_each_value():
    apps = _deployment_lister("checkout-api", "unrelated-worker")
    core = _core_with(configmaps={"checkout-files": {"app.yaml": "...", "features.json": "..."}})

    def _api(kind, context=None):
        return apps if kind == "AppsV1Api" else core

    with patch("app.services.presweep.k8s_service._get_api", side_effect=_api), \
         patch("app.tools.k8s_tools.get_workload_config",
               AsyncMock(return_value=_WORKLOAD_CONFIG)):
        out = await build_config_sources("payments", "set checkout-api log level to debug")

    assert "configmap/checkout-config key 'log_level'" in out
    assert "envFrom: configmap/checkout-flags" in out
    assert "configmap/checkout-files at /etc/app" in out
    assert "app.yaml" in out                      # key names, so "it's in a file" is answerable
    assert "unrelated-worker" not in out          # scoped to what the query named
    assert "write to the object that OWNS it" in out


@pytest.mark.asyncio
async def test_memory_limit_reaches_context_beside_the_env_vars():
    """The checkoutapi case: asked to fix an OOMKilled pod, the agent proposed
    patching a .NET GC env var. It was not being dumb — the 40-entry env list was
    in its context and the memory limit was not, because resources lived only in
    describe_pod_scheduling. The limit is the fix; it has to be handed over too."""
    import copy
    config = copy.deepcopy(_WORKLOAD_CONFIG)
    config["data"]["containers"][0]["limits"] = {"memory": "50Mi"}
    config["data"]["containers"][0]["requests"] = {"memory": "50Mi"}
    apps = _deployment_lister("checkout-api")
    core = _core_with(configmaps={"checkout-files": {}})

    def _api(kind, context=None):
        return apps if kind == "AppsV1Api" else core

    with patch("app.services.presweep.k8s_service._get_api", side_effect=_api), \
         patch("app.tools.k8s_tools.get_workload_config",
               AsyncMock(return_value=config)):
        out = await build_config_sources("payments", "fix the OOM in checkout-api")

    assert "50Mi" in out
    assert "patch_deployment_resources" in out


@pytest.mark.asyncio
async def test_config_sources_empty_when_query_names_no_workload():
    """No workload named — costs one list call and adds nothing to context."""
    apps = _deployment_lister("checkout-api")
    with patch("app.services.presweep.k8s_service._get_api", side_effect=lambda k, context=None: apps):
        assert await build_config_sources("payments", "is the cluster healthy") == ""


@pytest.mark.asyncio
async def test_config_sources_survives_a_dead_cluster():
    """Mock mode / no kubeconfig must not break a chat turn."""
    with patch("app.services.presweep.k8s_service._get_api", return_value=None):
        assert await build_config_sources("payments", "change checkout-api log level") == ""


# ── layer 3: the tool that acts on the owner must be reachable ───────────────
#
# Found by running the eval: the agent identified configmap/checkout-config
# correctly and then said "I don't have a write tool here" — which was TRUE.
# update_configmap is not in _CORE_K8S, "set" is not a write keyword, and
# _score_tool counts query words appearing in a tool's description, so
# "set the log level to debug for checkout-api in payments" scores it 0. Its
# only route in was the discover_tools escape hatch, taken inconsistently.

_CONFIG_QUERY = "set the log level to debug for checkout-api in payments"


def _schema():
    from app.tools.registry import TOOL_REGISTRY
    return [{"type": "function",
             "function": {"name": n, "description": d.get("description", ""),
                          "parameters": {"type": "object", "properties": {}, "required": []}}}
            for n, d in TOOL_REGISTRY.items()]


def _selected(force, **kw):
    from app.services.ai_service import AIService
    return {t["function"]["name"] for t in AIService._select_dynamic_tools(
        _CONFIG_QUERY, [], _schema(), [], [], force_tools=force, **kw)}


def test_config_write_tool_scores_zero_on_a_natural_phrasing():
    """The measurement behind the fix — if this ever starts scoring, the force
    list may be redundant and should be re-examined rather than left to rot."""
    from app.services.ai_service import AIService
    tool = next(t for t in _schema() if t["function"]["name"] == "update_configmap")
    assert AIService._score_tool(set(_CONFIG_QUERY.split()), tool) == 0
    assert "update_configmap" not in AIService._CORE_K8S


def test_without_the_owner_map_config_tools_are_absent():
    """Documents the unfixed behaviour: this is what the agent actually faced."""
    assert _selected(frozenset()).isdisjoint({"update_configmap", "get_configmap",
                                              "get_workload_config"})


def test_owner_map_makes_the_config_tools_reachable():
    from app.services.ai_service import AIService
    assert AIService._CONFIG_OWNER_TOOLS <= _selected(AIService._CONFIG_OWNER_TOOLS)


def test_forced_tools_survive_the_cap():
    """A forced tool scores 0, so without protection the cap evicts it first.

    Cap chosen above the protected floor (17 core + 3 forced + discover_tools) but
    below the uncapped selection, so the cap genuinely bites on unprotected tools.
    A cap at or below the floor truncates inside the protected set itself — that is
    a pre-existing property of the cap, not something this change introduces.
    """
    from app.services.ai_service import AIService
    got = _selected(AIService._CONFIG_OWNER_TOOLS, max_total=24)
    assert len(got) <= 24
    assert AIService._CONFIG_OWNER_TOOLS <= got
    assert "discover_tools" in got  # the existing escape hatch must also survive


def test_forcing_does_not_disturb_the_rest_of_the_selection():
    """Only the forced names are added — no widening of unrelated selection."""
    from app.services.ai_service import AIService
    base = _selected(frozenset())
    forced = _selected(AIService._CONFIG_OWNER_TOOLS)
    assert forced - base == set(AIService._CONFIG_OWNER_TOOLS)


@pytest.mark.asyncio
async def test_config_sources_is_not_parsed_as_a_sweep_finding():
    """build_config_sources output must never reach append_missing_findings' _BULLET
    regex, but if it ever does, its lines must not look like unreported findings —
    otherwise every answer gets the whole owner map stapled to the end."""
    from app.services.presweep import sweep_subjects

    apps = _deployment_lister("checkout-api")
    core = _core_with(configmaps={"checkout-files": {"app.yaml": "..."}})

    def _api(kind, context=None):
        return apps if kind == "AppsV1Api" else core

    with patch("app.services.presweep.k8s_service._get_api", side_effect=_api), \
         patch("app.tools.k8s_tools.get_workload_config",
               AsyncMock(return_value=_WORKLOAD_CONFIG)):
        out = await build_config_sources("payments", "set checkout-api log level to debug")

    assert sweep_subjects(out) == []
