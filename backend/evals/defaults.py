"""Default fixture responses for the always-on core K8s tools.

`AIService._CORE_K8S` (app/services/ai_service.py) is injected into the tool
schema for every query regardless of routing, so the agent can reach for any
of these 17 names in any scenario -- including the ones that scenario author
never anticipated needing. Before this module, a scenario that did not
fixture one of them got `harness._fixture_server`'s generic miss:

    {"success": False, "error": "eval: no fixture for 'search_topology' ..."}

The model reads that as a broken environment, not a normal "nothing here" --
three live runs showed it giving up mid-investigation over exactly this. In
production the tool would have returned real (possibly empty) data instead.

Each function below returns what the real tool returns for its own "nothing
to report" case -- an empty list/dict for a listing tool, the tool's own
"not found" text for a single-target lookup, the `_pending_confirmation`
envelope for a write op that always asks before acting. Never a fabricated
resource, never richer than what production would say for a genuine miss
(the same rule scenarios/README.md holds fixtures to). The source line each
one mirrors is cited in its docstring/comment.

Scenario-declared fixtures in `cluster:` always win -- `_fixture_server`
checks `scenario.cluster` first. A tool that is neither fixtured nor in
`CORE_TOOL_DEFAULTS` is a genuinely unrecognised call and still gets the
explicit "no fixture" miss, so a scenario author learns what they missed
instead of it being silently papered over.
"""
from typing import Any, Callable, Dict, Optional


def _get_cluster_health(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:204-214 -- the healthy/empty-cluster shape.
    return {
        "success": True,
        "data": {
            "node_count": 0, "ready_nodes": 0, "pod_count": 0,
            "running_pods": 0, "pending_pods": 0,
            "unhealthy_pod_count": 0, "unhealthy_pods": [],
            "status": "Healthy",
        },
        "error": None, "source": "k8s_client",
    }


def _search_pods(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:279 -- data is a bare list, empty when nothing matches.
    return {"success": True, "data": [], "error": None, "source": "k8s_client"}


def _get_pod_logs(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:356-360 -- the real "pod not found" miss (namespace
    # omitted, _find_pod_namespace comes back empty).
    pod_name = inputs.get("pod_name", "unknown")
    return {
        "success": False, "data": None,
        "error": f"Pod '{pod_name}' not found in any namespace",
        "source": "k8s_client",
    }


def _get_pod_events(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:388-392 -- identical miss shape to get_pod_logs.
    pod_name = inputs.get("pod_name", "unknown")
    return {
        "success": False, "data": None,
        "error": f"Pod '{pod_name}' not found in any namespace",
        "source": "k8s_client",
    }


def _describe_pod(inputs: dict) -> Dict[str, Any]:
    # app/services/k8s_service.py:474-477 -- get_pod_details catches the 404
    # itself and returns an "Error getting pod details: ..." string; describe_pod
    # (app/tools/k8s_tools.py:2261-2267) never sees an exception to propagate,
    # so the envelope is success=True with that string as data. The real `{e}`
    # is an ApiException repr this default cannot reproduce verbatim.
    pod_name = inputs.get("pod_name", "unknown")
    return {
        "success": True,
        "data": f"Error getting pod details: pod '{pod_name}' not found.",
        "error": None, "source": "k8s_client",
    }


def _get_node_status(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:455-469 -- data is a bare list, one entry per node.
    return {"success": True, "data": [], "error": None, "source": "k8s_client"}


def _list_namespaces(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:1794-1802
    return {"success": True, "data": {"namespaces": [], "total": 0}, "error": None, "source": "k8s_client"}


def _diagnose_pod(inputs: dict) -> Dict[str, Any]:
    # app/services/diagnostic_service.py:737-755, wrapped success=True at
    # app/tools/k8s_tools.py:2777-2790 (diagnose_pod_tool never sees the
    # "not found" case as a failure -- it is the function's normal return).
    pod_name = inputs.get("pod_name", "unknown")
    namespace = inputs.get("namespace")
    text = (f"DIAGNOSIS: {pod_name} — Pod not found in namespace '{namespace}'"
            if namespace else f"DIAGNOSIS: {pod_name} — Pod not found")
    return {"success": True, "data": text, "error": None, "source": "diagnostic_engine"}


def _diagnose_service(inputs: dict) -> Dict[str, Any]:
    # app/services/diagnostic_service.py:790-809, wrapped success=True at
    # app/tools/k8s_tools.py:2793-2805.
    service_name = inputs.get("service_name", "unknown")
    namespace = inputs.get("namespace")
    text = (f"DIAGNOSIS: service/{service_name} — Service not found in namespace '{namespace}'"
            if namespace else f"DIAGNOSIS: service/{service_name} — Service not found")
    return {"success": True, "data": text, "error": None, "source": "diagnostic_engine"}


def _search_topology(inputs: dict) -> Dict[str, Any]:
    # app/services/topology_service.py:466-467, wrapped success=True at
    # app/tools/k8s_tools.py:2742-2757.
    query = inputs.get("query", "")
    return {"success": True, "data": f"No topology matches found for '{query}'", "error": None, "source": "topology"}


def _pending(tool_name: str, message: str, risk_level: str, tool_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:1922-1936 (_pending_confirmation) -- the exact
    # envelope every write tool returns before confirmed=True, independent of
    # whether the target exists. Not an approximation: this IS what production
    # returns on the first call to any of these three tools.
    return {
        "success": True, "data": None, "error": None, "source": "k8s_client",
        "requires_confirmation": True,
        "pending_operation": {
            "tool_name": tool_name, "tool_inputs": tool_inputs,
            "confirmation_message": message, "risk_level": risk_level,
        },
    }


def _scale_deployment(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:2107-2118
    name = inputs.get("deployment_name", "unknown")
    replicas = inputs.get("replicas", "unknown")
    reason = inputs.get("reason", "")
    msg = (f"The AI wants to scale deployment '{name}' from unknown to {replicas} replicas.\n\n"
           f"Reason: {reason}\n\nApprove or cancel?")
    return _pending("scale_deployment", msg, "medium", inputs)


def _create_namespace(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:2130-2137
    namespace = inputs.get("namespace", "unknown")
    reason = inputs.get("reason", "")
    msg = (f"The AI wants to create namespace '{namespace}'.\n\n"
           f"Reason: {reason}\n\n"
           f"This will create a new Kubernetes namespace. Approve or cancel?")
    return _pending("create_namespace", msg, "low", inputs)


def _deploy_application(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:2150-2171
    name = inputs.get("name", "unknown")
    image = inputs.get("image", "unknown")
    namespace = inputs.get("namespace", "unknown")
    replicas = inputs.get("replicas", 1)
    reason = inputs.get("reason", "")
    msg = (f"The AI wants to deploy application '{name}' (image: {image}) "
           f"with {replicas} replica(s) in namespace '{namespace}'.\n\n"
           f"Reason: {reason}\n\n"
           f"This will create a Deployment and a ClusterIP Service. Approve or cancel?")
    return _pending("deploy_application", msg, "medium", inputs)


def _list_services(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:992-1017
    return {"success": True, "data": {"services": [], "total": 0}, "error": None, "source": "k8s_client"}


def _get_endpoints(inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:1039-1063 -- the real "not found" miss.
    service_name = inputs.get("service_name", "unknown")
    namespace = inputs.get("namespace") or "all namespaces"
    return {
        "success": False, "data": None,
        "error": f"Endpoints '{service_name}' not found in {namespace}",
        "source": "k8s_client",
    }


def _list_deployments(_inputs: dict) -> Dict[str, Any]:
    # app/tools/k8s_tools.py:2274-2295
    return {"success": True, "data": {"deployments": [], "count": 0}, "error": None, "source": "k8s_client"}


def _fix_image_pull(inputs: dict) -> Dict[str, Any]:
    # app/tools/registry.py:79-86 -- the real "could not read pod" miss.
    # The real `{e}` is an ApiException repr this default cannot reproduce
    # verbatim, so the message body says "not found" instead.
    pod_name = inputs.get("pod_name", "unknown")
    namespace = inputs.get("namespace", "unknown")
    return {
        "success": False,
        "error": f"Could not read pod '{pod_name}' in '{namespace}': not found",
        "source": "fix_image_pull",
    }


# One entry per name in AIService._CORE_K8S (app/services/ai_service.py). Kept
# as an explicit dict, not derived from that set at import time, so a rename
# there breaks import instead of silently going undefaulted; the two sets'
# equality is asserted by a test in tests/test_evals_harness.py so they
# cannot drift apart unnoticed.
CORE_TOOL_DEFAULTS: Dict[str, Callable[[dict], Dict[str, Any]]] = {
    "get_cluster_health": _get_cluster_health,
    "search_pods": _search_pods,
    "get_pod_logs": _get_pod_logs,
    "get_pod_events": _get_pod_events,
    "describe_pod": _describe_pod,
    "get_node_status": _get_node_status,
    "list_namespaces": _list_namespaces,
    "diagnose_pod": _diagnose_pod,
    "diagnose_service": _diagnose_service,
    "search_topology": _search_topology,
    "scale_deployment": _scale_deployment,
    "deploy_application": _deploy_application,
    "create_namespace": _create_namespace,
    "list_services": _list_services,
    "get_endpoints": _get_endpoints,
    "list_deployments": _list_deployments,
    "fix_image_pull": _fix_image_pull,
}


def core_tool_default(tool_name: str, inputs: dict) -> Optional[Dict[str, Any]]:
    """The default response for `tool_name`, or None if it is not an
    always-on core tool -- i.e. a genuinely unfixtured/unrecognised call that
    must still surface as an explicit miss rather than being papered over."""
    factory = CORE_TOOL_DEFAULTS.get(tool_name)
    return factory(inputs) if factory else None
