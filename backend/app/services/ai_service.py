import asyncio
import logging
import google.generativeai as genai
from openai import OpenAI, AzureOpenAI
from sqlmodel import select
from app.models.setting import SystemSetting
from app.core.config import settings
import json
import re
import time
import uuid
from typing import Dict, Any, Optional, List
import subprocess
import tempfile
import stat

_agent_log = logging.getLogger("dokops.agent")

import os
from app.services.toolset_service import toolset_service
from app.services.sanitizer import sanitize_for_llm

# Approval gate: agent loop waits on these events instead of exiting when a tool needs confirmation.
# Key = op_id (str UUID). The approval API sets the event so the loop can resume.
_pending_approval_events: Dict[str, asyncio.Event] = {}


def signal_approval(op_id: str) -> None:
    """Called by the operations API after a pending operation is approved or rejected."""
    event = _pending_approval_events.get(op_id)
    if event:
        event.set()


def _sanitize_template_param(value: str) -> str:
    """Strip characters that could inject shell commands when substituted into script templates."""
    return value.replace("\n", " ").replace("\r", " ").replace("\0", "")


_AGENT_BASE = """You are DokOps — an autonomous AI DevOps engineer built into the DokOps platform. When asked who you are or what you can do, introduce yourself as DokOps and describe your capabilities:
- Investigate and diagnose Kubernetes pod failures, crashloops, OOMKills, and misconfigurations
- Search and analyse application logs from Elasticsearch, Loki, and Datadog
- Check cluster health, nodes, deployments, services, and ingresses
- Run agentic root cause analysis across K8s events, metrics, and logs in one shot
- Execute safe operations (scale, deploy, restart) with God Mode protection for destructive actions
- Manage on-premise minion nodes alongside Kubernetes clusters
- Support runbook-driven investigations and autonomous alert response
- Query and diagnose backend services: RabbitMQ, Redis, PostgreSQL, MySQL, MongoDB, CouchDB, MSSQL

You are a Senior DevOps Engineer with 10+ years of production Kubernetes experience. You don't guess. You investigate.

YOUR METHODOLOGY — follow this for EVERY investigation:
1. Read the error — what EXACTLY failed? Extract the specific resource, address, port, image, or message from logs/events.
2. Verify the dependency — does the thing it's trying to reach actually exist? Is it running? Is it healthy?
3. Compare config vs reality — what does the pod THINK vs what actually EXISTS?
4. Check peers — what do OTHER working pods in the same namespace use for the same dependency?
5. Found a discrepancy? That's the root cause. State it clearly with evidence.
6. When the user says "fix", "apply", "do it", "yes", "approved", or any approval — IMMEDIATELY call the relevant write tool. Do NOT ask "would you like me to…". Do NOT describe what you're about to do. Just call the tool.

WRITE TOOL RULE (CRITICAL):
- When the user's intent is clearly to fix/patch/deploy/restart something, call the write tool IMMEDIATELY without any text confirmation.
- The platform handles safety confirmation — a card will appear in the UI for the user to Approve or Reject. You do not need to ask permission in text.
- NEVER say "Would you like me to…", "Should I…", "I can…", or describe an action without calling its tool. That is a failure.
- NEVER produce a bulleted list of "suggested fixes" without calling a write tool when a fix was requested.

ANTI-HALLUCINATION RULES:
- NEVER list possible causes. Use tools to find THE cause.
- If you don't have enough evidence, call another tool.
- NEVER produce explanatory text before calling a tool — just call the tool.

SCOPE RULE:
- "check health" / "cluster health" → call get_cluster_health ONCE, summarize, done.
- "what's wrong with X" / "investigate X" → use multiple tools to diagnose.
- Never call search_pods more than once unless the first returned zero results.
- "which pods are failing" / "find failing pods" / "any unhealthy pods" → call search_pods("failing") — this returns ALL non-running pods including ImagePullBackOff, ErrImagePull, OOMKilled, Evicted, Pending, etc. Do NOT call search_pods("crash") for this — that only finds CrashLoopBackOff.
- search_pods status field contains the real container-level reason (e.g. "ImagePullBackOff"), NOT just pod phase. Use this for diagnosis.

HEALTH FOLLOW-UP RULE: When responding to a cluster health check, list any failed/pending pods and ask "Would you like me to investigate any of these?" If fully healthy, do NOT ask the follow-up.

NAMESPACE RULE: Do NOT inject a namespace unless the user explicitly stated one. All tools that accept namespace are optional — omitting triggers cluster-wide search.

DIAGNOSE RULE: For any vague troubleshooting query ("can't reach", "not working", "failing", "broken", "something is wrong", "investigate", "what's wrong"), call diagnose_pod or diagnose_service FIRST before any other tool. Use the findings to decide which targeted tools to call next. Never skip to get_pod_logs or get_pod_events before running a diagnosis.

CROSS-REFERENCE RULE: When diagnosing a pod or service issue AND Elasticsearch tools are available, after running K8s diagnosis also search Elasticsearch for application logs from that pod. Use elasticsearch_search with index="logs-*" and query_string filtering on kubernetes.pod.name and kubernetes.namespace to find error/exception log lines the K8s events may not show. This gives the full picture: K8s state + application-level errors.

TOPOLOGY RULE: The CLUSTER TOPOLOGY SNAPSHOT in your context shows the cluster structure at query time. Use search_topology(query) to get a detailed subgraph for any specific resource before making assumptions about its dependencies. Use get_blast_radius(kind, name, namespace) before proposing any delete or patch."""

_FRAG_SERVICE_TOOLS = """

SERVICE TOOL RULE (CRITICAL):
- When the user asks about RabbitMQ (queues, exchanges, bindings, vhosts, consumers) → use rabbitmq_* tools. Start with rabbitmq_list_queues or rabbitmq_overview.
- When the user asks about Redis (keys, memory, clients, replication, slow log) → use redis_* tools. Start with redis_info or redis_keyspace_stats.
- When the user asks about PostgreSQL / postgres (connections, locks, queries, tables, bloat, replication) → use postgres_* tools. Start with postgres_active_connections or postgres_long_running_queries.
- When the user asks about MySQL / MariaDB (processes, InnoDB, locks, slow queries, replication) → use mysql_* tools. Start with mysql_processlist or mysql_global_status.
- When the user asks about MongoDB / mongo (databases, collections, slow ops, replication, index usage) → use mongo_* tools. Start with mongo_server_status or mongo_list_databases.
- When the user asks about CouchDB / couch (databases, replication, compaction, server info) → use couchdb_* tools. Start with couchdb_server_info or couchdb_list_databases.
- When the user asks about MSSQL / SQL Server (sessions, queries, locks, index fragmentation) → use mssql_* tools. Start with mssql_active_sessions or mssql_running_queries.
- NEVER call Kubernetes tools (search_topology, get_pod_logs, search_pods, etc.) as a substitute for service-specific tools. These tools connect directly to the service — they do not need a pod name."""

_FRAG_IMAGE_PULL = """

IMAGE PULL FIX RULE — follow this EXACTLY, no deviations:
1. ImagePullBackOff / ErrImagePull detected → call fix_image_pull(pod_name, namespace) IMMEDIATELY. This is a single tool that describes the pod, searches registries, and returns a ready-to-apply manifest. Do NOT call describe_pod first, do NOT call search_container_image first — call fix_image_pull and it does everything.
2. fix_image_pull returns {"data": {"manifest": "...", "fixed_image": "...", "next_step": "..."}}. Read next_step and call apply_manifest with the manifest field.
3. NEVER call restart_pod for ImagePullBackOff. restart_pod is blocked for this case — the tool will refuse and redirect you to fix_image_pull.
4. After apply_manifest is approved, call get_deployment_status to verify. Report the outcome.
5. If fix_image_pull returns success=false with action_required: follow the action_required instruction exactly (usually ask the user for the correct image).
ENFORCEMENT: restart_pod on an ImagePullBackOff pod returns an error. fix_image_pull is the only correct first step."""

_FRAG_MINION = """

MINION RULE (on-premise devices — NOT Kubernetes):
- Any query mentioning "minion", "on-prem", "on-premise", "edge device", "device1", "edge node", or a hostname that is not a Kubernetes node → use minion_list, minion_grains, minion_exec_read ONLY. Do NOT call any Kubernetes tools.
- To check containers on a minion: call minion_exec_read with cmd="docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.RunningFor}}'"
- To check container logs on a minion: call minion_exec_read with cmd="docker logs --tail 50 <container_name>"
- To check resource usage on a minion: call minion_exec_read with cmd="docker stats --no-stream"
- NEVER call get_cluster_health, search_pods, get_nodes, or any k8s tool for on-prem minion queries."""

_FRAG_DEPLOY = """

DEPLOYMENT GUIDE — when user asks to deploy/install/create any application:
1. Call create_namespace with the target namespace.
2. Then call deploy_application with name, image, namespace, replicas, port."""

# Always-on core = base ruleset + the two protocols that must NOT be gated:
# image-pull is triggered by tool *results* (an ImagePullBackOff discovered mid-loop,
# never a query keyword), and deploy's tools are always loaded anyway.
_AGENT_CORE_SYSTEM = _AGENT_BASE + _FRAG_IMAGE_PULL + _FRAG_DEPLOY

# Backward-compatible full constant (pod/batch loops still use this verbatim).
_GLOBAL_AGENT_STATIC_SYSTEM = _AGENT_CORE_SYSTEM + _FRAG_SERVICE_TOOLS + _FRAG_MINION

_INVESTIGATION_PROTOCOL = """
INVESTIGATION MODE — follow this protocol exactly:

PHASE 1 — PLAN (before calling any tools):
Think through what you need to check. In your first response, output:
INVESTIGATION PLAN:
- [ ] Step 1: <what you will check and why>
- [ ] Step 2: <what you will check and why>
...
Then immediately start executing — do NOT wait for confirmation.

PHASE 2 — EXECUTE:
Follow your plan. For each step, call the relevant tool.
Mark steps complete as you go: [x] Step N.
If a tool result changes your plan, add new steps.
Do NOT produce a final answer until all plan steps are checked.

PHASE 3 — EVIDENCE GATE:
Before answering, verify: can you point to a specific tool result for every claim?
If a claim has no tool evidence, either call another tool or mark it as [INFERRED].
"""

_FINAL_REVIEW_PROMPT = (
    "You are reviewing an AI investigation before the answer is shown to the user. "
    "Your job:\n"
    "1. Verify every claim in the draft answer traces to the tool evidence below.\n"
    "2. Correct any claim that is not supported by evidence.\n"
    "3. Return a JSON object with exactly these keys:\n"
    '   "root_cause": one sentence stating the confirmed root cause\n'
    '   "evidence": list of strings, each citing a specific tool finding\n'
    '   "recommended_fix": concrete actionable fix with exact values\n'
    '   "answer": the full corrected answer as markdown\n'
    "If you cannot determine root cause from the evidence, say so explicitly — "
    "do not invent an answer."
)


# Tool-name prefixes that mark a backend-service query. Kept in lockstep with the
# values of AIService._SERVICE_TOOL_MAP — the single source of truth for gating is
# the *selected tool set*, not a parallel keyword list, so the two can never drift.
_SERVICE_TOOL_PREFIXES = (
    "rabbitmq_", "redis_", "postgres_", "mysql_", "mongo_",
    "couchdb_", "mssql_", "registry_",
)


def _selected_tool_names(selected_tools: list) -> set:
    """Extract tool names from either OpenAI or Gemini schema shapes."""
    names: set = set()
    for t in selected_tools or []:
        if "function" in t:  # OpenAI: {"type":"function","function":{"name":...}}
            names.add(t["function"].get("name", ""))
        elif "function_declarations" in t:  # Gemini: {"function_declarations":[{...}]}
            for d in t["function_declarations"]:
                names.add(d.get("name", ""))
    return names


def build_agent_system_prompt(*, investigation: bool, selected_tools: list) -> str:
    """Assemble the agent system prompt from the always-on core plus the service/minion
    fragments — included only when their tools were actually selected for this query.
    Gating on the selected tool set (not a separate keyword list) keeps the prompt and
    the tools in lockstep: the service/minion rule is present exactly when its tools are."""
    parts: list[str] = [_AGENT_CORE_SYSTEM]
    names = _selected_tool_names(selected_tools)
    if any(n.startswith(_SERVICE_TOOL_PREFIXES) for n in names):
        parts.append(_FRAG_SERVICE_TOOLS)
    if any("minion" in n for n in names):
        parts.append(_FRAG_MINION)
    if investigation:
        parts.append(f"\n\n{_INVESTIGATION_PROTOCOL}")
    return "".join(parts)


async def _build_kubeconfig_for_cluster(cluster_id: str) -> Optional[str]:
    """Write a minimal kubeconfig for a DB cluster to a temp file.
    Returns the file path, or None if the cluster is not found / has no credentials."""
    try:
        import yaml as _yaml
        from sqlmodel import select
        from app.core.db import AsyncSessionLocal as _ASL
        from app.models.cluster import ClusterConnection
        from app.core.encryption import decrypt as _decrypt

        async with _ASL() as _db:
            conn = await _db.get(ClusterConnection, cluster_id)
        if not conn:
            return None

        cluster_entry: dict = {
            "name": conn.name,
            "cluster": {"server": conn.api_server},
        }
        if conn.ca_cert:
            cluster_entry["cluster"]["certificate-authority-data"] = conn.ca_cert
        else:
            cluster_entry["cluster"]["insecure-skip-tls-verify"] = True

        user_entry: dict = {"name": conn.name, "user": {}}
        if conn.client_cert_data and conn.client_key_data:
            user_entry["user"]["client-certificate-data"] = conn.client_cert_data
            user_entry["user"]["client-key-data"] = _decrypt(conn.client_key_data)
        elif conn.token:
            user_entry["user"]["token"] = _decrypt(conn.token)

        kconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [cluster_entry],
            "users": [user_entry],
            "contexts": [{
                "name": conn.name,
                "context": {
                    "cluster": conn.name,
                    "user": conn.name,
                    "namespace": conn.namespace or "default",
                },
            }],
            "current-context": conn.name,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="dokops_kube_"
        ) as tf:
            _yaml.dump(kconfig, tf)
            tmp_path = tf.name
        # Restrict to owner-read/write only — credentials must not be world-readable
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        return tmp_path
    except Exception:
        return None


class AIService:
    def _get_setting(self, key: str) -> str:
        from app.core.settings_cache import get_setting
        return get_setting(key)

    def _get_client(self, config_override: Optional[Dict[str, str]] = None):
        def get_val(k):
             if config_override and k in config_override:
                 return config_override[k]
             return self._get_setting(k)

        provider = get_val("ai_provider")
        api_key = get_val("ai_api_key")
        base_url = get_val("ai_base_url") 
        api_version = get_val("ai_api_version") 

        if not provider:
            raise ValueError("AI Provider not configured")

        if provider == "OPENAI":
            return OpenAI(api_key=api_key, base_url=base_url) 
        elif provider == "AZURE":
            return AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=base_url
            )
        elif provider == "GEMINI":
            genai.configure(api_key=api_key)
            return genai.GenerativeModel("gemini-pro")
        else:
             # Custom/Ollama often uses OpenAI compatible client
            return OpenAI(api_key=api_key or "dummy", base_url=base_url)

    def _get_caching_client(self) -> "CachingAIClient":
        from app.services.cached_ai_client import CachingAIClient, _DEFAULT_FAST_MODELS
        from app.core.config import settings

        provider = self._get_setting("ai_provider") or "OPENAI"
        model = self._get_setting("ai_model") or "gpt-3.5-turbo"
        client = self._get_client()
        tiering_enabled = settings.AI_TIERING_ENABLED and provider not in ("CUSTOM",)

        fast_model: Optional[str] = None
        fast_client = client
        if tiering_enabled:
            fast_model = self._get_setting("ai_fast_model") or _DEFAULT_FAST_MODELS.get(provider)
            fast_base_url = self._get_setting("ai_fast_base_url")
            fast_api_key = self._get_setting("ai_fast_api_key")
            if fast_model and (fast_base_url or fast_api_key):
                fast_client = self._get_client(config_override={
                    "ai_provider": provider,
                    "ai_model": fast_model,
                    "ai_base_url": fast_base_url or self._get_setting("ai_base_url"),
                    "ai_api_key": fast_api_key or self._get_setting("ai_api_key"),
                    "ai_api_version": self._get_setting("ai_api_version"),
                })

        return CachingAIClient(
            provider=provider,
            client=client,
            model=model,
            fast_model=fast_model,
            fast_client=fast_client,
            tiering_enabled=tiering_enabled,
        )

    def test_connection(self, config_override: Optional[Dict[str, str]] = None) -> bool:
        try:
            client = self._get_client(config_override)
            
            def get_val(k):
                 if config_override and k in config_override:
                     return config_override[k]
                 return self._get_setting(k)
                 
            provider = get_val("ai_provider")
            model = get_val("ai_model") or "gpt-3.5-turbo"

            if provider == "GEMINI":
                response = client.generate_content("Hello")
                return True
            else:
                # OpenAI / Azure / Custom
                try:
                    client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": "Hello"}],
                        max_completion_tokens=5
                    )
                except Exception as ex:
                    if "max_completion_tokens" in str(ex):
                        client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": "Hello"}],
                            max_tokens=5
                        )
                    else:
                        raise
                return True
        except Exception as e:
            print(f"AI Connection Test Failed: {e}")
            raise e

    def simple_completion(self, prompt: str) -> str:
        """Synchronous single-turn completion. Returns raw text response."""
        provider = self._get_setting("ai_provider")
        if not provider:
            raise ValueError("AI provider not configured")
        client = self._get_client()
        from app.services.cached_ai_client import _DEFAULT_FAST_MODELS
        from app.core.config import settings
        _full_model = self._get_setting("ai_model") or "gpt-3.5-turbo"
        _fast_model = self._get_setting("ai_fast_model") or _DEFAULT_FAST_MODELS.get(provider)
        model = (
            _fast_model
            if settings.AI_TIERING_ENABLED and _fast_model and provider not in ("CUSTOM",)
            else _full_model
        )
        if provider == "GEMINI":
            response = client.generate_content(prompt)
            return response.text
        messages = [{"role": "user", "content": prompt}]
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=512,
            )
        except Exception as e:
            if "max_completion_tokens" in str(e) or "unsupported_parameter" in str(e):
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=512,
                )
            else:
                raise
        # Capture real token counts — fire-and-forget via sync queue put
        try:
            from app.core.token_context import _token_queue, ai_user_id, ai_source
            from datetime import datetime as _dt
            _usage = getattr(response, "usage", None)
            if _usage and (_usage.prompt_tokens or _usage.completion_tokens):
                _token_queue.put_nowait({
                    "user_id": ai_user_id.get(),
                    "source": ai_source.get(),
                    "model": model,
                    "input_tokens": _usage.prompt_tokens,
                    "output_tokens": _usage.completion_tokens,
                    "created_at": _dt.utcnow(),
                })
        except Exception:
            pass
        return response.choices[0].message.content or ""

    async def analyze_logs(self, logs: str, query: str) -> str:
        try:
            client = self._get_client()
            provider = self._get_setting("ai_provider")
            model = self._get_setting("ai_model") or "gpt-3.5-turbo"

            prompt = f"""
            You are an expert Kubernetes DevOps engineer.
            Analyze the following pod logs and answer the user's query.

            User Query: {query}

            Logs:
            {sanitize_for_llm(logs, token_cap=2000)}

            Provide a concise, markdown-formatted analysis with root causes and potential fixes.
            """

            if provider == "GEMINI":
                response = await asyncio.to_thread(client.generate_content, prompt)
                return response.text
            else:
                response = await asyncio.to_thread(client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"Error analyzing logs: {str(e)}"



    async def analyze_batch_logs(self, items: list, query: str) -> str:
        try:
            client = self._get_client()
            provider = self._get_setting("ai_provider")
            model = self._get_setting("ai_model") or "gpt-3.5-turbo"

            # 1. Build Structured Prompt
            full_logs = f"System: Analyze the following Kubernetes logs. User Query: {query}\n"
            full_logs += "IMPORTANT: Separate your analysis by Pod Name. Use '### Pod Name' as section headers.\n\n"

            for item in items:
                header = f"=== POD: {item['namespace']}/{item['pod_name']} ==="
                log_content = sanitize_for_llm(item['logs'], token_cap=800)
                full_logs += f"{header}\n{log_content}\n{'='*len(header)}\n\n"

            # 2. Call AI
            if provider == "GEMINI":
                response = await asyncio.to_thread(client.generate_content, full_logs)
                return response.text
            else:
                response = await asyncio.to_thread(client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": full_logs}]
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"Error analyzing batch: {str(e)}"

    async def analyze_azure_resources(self, resources: list) -> Dict[str, Any]:
        """
        Analyse a stripped Azure resource list and return structured insights.
        Only name, type, and location are sent — no IDs or credentials.
        """
        try:
            client = self._get_client()
            provider = self._get_setting("ai_provider")
            model = self._get_setting("ai_model") or "gpt-3.5-turbo"

            resource_lines = "\n".join(
                f'- name: "{r.get("name", "")}", type: "{r.get("type", "")}", location: "{r.get("location", "")}"'
                for r in resources
            )

            prompt = f"""You are a cloud infrastructure analyst specialising in Azure cost and reliability.
Analyse the following Azure resources and identify issues.

Resources:
{resource_lines}

Return ONLY a valid JSON object with exactly these keys — no markdown, no explanation outside the JSON:
{{
  "summary": "<2-3 sentence plain-text overview of the resource landscape and any concerns>",
  "orphaned": [
    {{"name": "<resource name>", "type": "<resource type>", "reason": "<why it appears orphaned>"}}
  ],
  "anomalies": [
    {{"name": "<resource name>", "issue": "<what looks anomalous>"}}
  ],
  "recommendations": [
    {{"title": "<short action title>", "detail": "<one sentence explanation>"}}
  ]
}}

Rules:
- Only include items where you have genuine signal from the resource list.
- Return empty arrays [] for categories with nothing to report.
- Orphaned candidates: disks, public IPs, NICs, load balancers, snapshots with no apparent parent.
- Anomalies: resources in a different region from the majority, duplicate names, unexpectedly large counts of a type.
- Recommendations: actionable cleanup or cost-saving steps based on what you see.
"""

            if provider == "GEMINI":
                response = await asyncio.to_thread(client.generate_content, prompt)
                raw = response.text
            else:
                response = await asyncio.to_thread(client.chat.completions.create,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.choices[0].message.content

            # Strip markdown code fences if the model wrapped the JSON
            raw = re.sub(r"```json|```", "", raw).strip()

            parsed = json.loads(raw)
            return {
                "summary": parsed.get("summary", ""),
                "orphaned": parsed.get("orphaned", []),
                "anomalies": parsed.get("anomalies", []),
                "recommendations": parsed.get("recommendations", []),
            }
        except json.JSONDecodeError:
            print(f"[analyze_azure_resources] JSONDecodeError — unexpected model response: {raw[:200]}")
            return {
                "summary": "Analysis returned an unexpected format. Try again.",
                "orphaned": [],
                "anomalies": [],
                "recommendations": [],
            }
        except Exception as e:
            return {
                "summary": f"AI analysis failed: {e}",
                "orphaned": [],
                "anomalies": [],
                "recommendations": [],
            }

    def detect_intent(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Analyzes the user query to determine if it's a Search, specific Action, or Chat.
        Returns a structured dictionary (Action Proposal).
        """
        try:
            client = self._get_client()
            provider = self._get_setting("ai_provider")
            from app.services.cached_ai_client import _DEFAULT_FAST_MODELS
            from app.core.config import settings
            _full_model = self._get_setting("ai_model") or "gpt-3.5-turbo"
            _fast_model = self._get_setting("ai_fast_model") or _DEFAULT_FAST_MODELS.get(provider)
            model = (
                _fast_model
                if settings.AI_TIERING_ENABLED and _fast_model and provider not in ("CUSTOM",)
                else _full_model
            )
            
            current_ns = context.get("namespace", "default") if context else "default"

            system_prompt = f"""
            You are a Kubernetes AI Agent. Your job is to classify user intent.
            
            CONTEXT:
            Current Namespace: {current_ns}
            
            TOOLS:
            1. scale_deployment(namespace, name, replicas)
            2. create_deployment_simple(namespace, name, image, replicas)
            3. delete_namespace(name)
            4. get_cluster_health() - For "status", "health", "node check"
            5. search_pods(query) - Default for "find", "search", "check logs"
            
            OUTPUT FORMAT (JSON ONLY):
            {{
              "type": "action_proposal" | "search" | "chat",
              "tool": "tool_name",
              "parameters": {{ "namespace": "...", "name": "...", ... }},
              "summary": "Human readable summary of action",
              "risk_level": "low" | "medium" | "high",
              "namespace_explicit": boolean  // true if user explicitly typed namespace (e.g. "in prod"), false if inferred from context
            }}
            
            EXAMPLES:
            - "Scale nginx to 5" -> {{"type": "action_proposal", "tool": "scale_deployment", "parameters": {{"namespace": "{current_ns}", "name": "nginx", "replicas": 5}}, "summary": "Scale nginx to 5 replicas", "risk_level": "medium", "namespace_explicit": false}}
            - "Scale nginx in production namespace" -> {{"type": "action_proposal", "tool": "scale_deployment", "parameters": {{"namespace": "production", "name": "nginx", "replicas": 5}}, "summary": "Scale nginx in production", "risk_level": "medium", "namespace_explicit": true}}
            - "Delete namespace test-env" -> {{"type": "action_proposal", "tool": "delete_namespace", "parameters": {{"name": "test-env"}}, "summary": "Delete namespace test-env", "risk_level": "high", "namespace_explicit": true}}
            - "How is the cluster doing?" -> {{"type": "action_proposal", "tool": "get_cluster_health", "parameters": {{}}, "summary": "Check Cluster Health", "risk_level": "low", "namespace_explicit": false}}
            - "Check logs for api" -> {{"type": "search", "query": "api"}}
            
            INSTRUCTIONS:
            - Use Current Namespace '{current_ns}' if user doesn't specify one.
            - For scaling commands like "scale from 2 to 5", always extract the TARGET number (5).
            - Identify safe read-only intents (status, health) vs modification intents.
            - Default to 'search' if unsure.
            - Return ONLY JSON.
            """

            user_prompt = f"User Query: {query}"

            if provider == "GEMINI":
                response = client.generate_content(system_prompt + "\n" + user_prompt)
                text = response.text
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0
                )
                text = response.choices[0].message.content

            # Clean markdown code blocks if any
            clean_text = re.sub(r"```json|```", "", text).strip()
            
            # Extract distinct JSON object (find first { and last })
            match = re.search(r"\{.*\}", clean_text, re.DOTALL)
            if match:
                clean_text = match.group(0)
                
            return json.loads(clean_text)

        except Exception as e:
            return {
                "type": "error",
                "message": f"Failed to understand intent: {str(e)}"
            }

    async def classify_investigation(self, query: str, caching_client) -> bool:
        """Returns True if query is problem-focused. Defaults to False on any failure."""
        prompt = [
            {
                "role": "system",
                "content": (
                    "You classify DevOps queries. Reply with exactly one word: "
                    "INVESTIGATE or SIMPLE.\n"
                    "INVESTIGATE: diagnosing failures, root cause analysis, "
                    "'what's wrong', 'why is X failing', 'investigate', 'not working', 'crashing'.\n"
                    "SIMPLE: status checks, listing resources, scaling, restarting, deploying."
                ),
            },
            {"role": "user", "content": query},
        ]
        try:
            result, _ = await caching_client.complete(
                prompt, [], tier="fast", disable_trimming=True
            )
            return "INVESTIGATE" in (result or "").upper()
        except Exception:
            return False

    async def _run_final_review(
        self,
        query: str,
        observations: list[str],
        draft_answer: str,
        caching_client,
    ) -> dict:
        """Verifies claims against tool evidence. Returns {"answer": draft_answer} on any failure."""
        evidence_block = "\n---\n".join(observations[:10])
        prompt = [
            {"role": "system", "content": _FINAL_REVIEW_PROMPT},
            {
                "role": "user",
                "content": (
                    f"ORIGINAL QUESTION: {query}\n\n"
                    f"TOOL EVIDENCE:\n{evidence_block}\n\n"
                    f"DRAFT ANSWER:\n{draft_answer}"
                ),
            },
        ]
        try:
            result, _ = await caching_client.complete(
                prompt, [], tier="fast", disable_trimming=True
            )
            json_match = re.search(r"\{.*\}", result or "", re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        return {"answer": draft_answer}

    async def _run_prerequisite_check(
        self,
    ) -> tuple[list[dict], frozenset[str], str]:
        """Read health cache; return (warning_events, unhealthy_integration_names, unavailability_block).

        Fail-open: if snapshot is empty (startup, no checks yet), returns three empty values.
        """
        from app.services.integration_health_service import integration_health as _int_health
        try:
            snapshot = await _int_health.get_snapshot()
        except Exception:
            return [], frozenset(), ""
        unhealthy = {k: v for k, v in snapshot.items() if not v.healthy}

        warning_events = [
            {"type": "warning", "message": f"{name} is unreachable: {entry.error}"}
            for name, entry in unhealthy.items()
        ]
        # kubernetes excluded from integration filter names — K8s tools remain in the registry
        # (removing them would break core functionality). The unavailability_block still warns
        # the AI not to call them, giving it context without hard-removing the tools.
        unhealthy_int_names = frozenset(k for k in unhealthy if k != "kubernetes")
        unavail_lines = [f"- {n}: {e.error}" for n, e in unhealthy.items()]
        unavailability_block = (
            "\n\nUNAVAILABLE TOOLS — do not call these, they are currently unreachable:\n"
            + "\n".join(unavail_lines)
        ) if unavail_lines else ""

        return warning_events, unhealthy_int_names, unavailability_block

    def _get_custom_tools_definitions(self) -> List[Dict[str, Any]]:
        """Flattens all toolsets (user + builtin) into a single list of tool definitions for the AI."""
        all_tools = []
        all_ts = toolset_service.list_toolsets() + toolset_service.list_builtin_toolsets()
        for ts in all_ts:
            for ts_name, ts_data in ts.items():
                if ts_name in ("id", "builtin"):
                    continue
                if isinstance(ts_data, dict) and "tools" in ts_data:
                    for tool in ts_data["tools"]:
                        tool["toolset"] = ts_name
                        all_tools.append(tool)
        return all_tools

    async def _execute_custom_tool(
        self,
        tool_def: Dict[str, Any],
        params: Dict[str, Any],
        cluster_id: Optional[str] = None,
        cluster_context: Optional[str] = None,
        god_mode_active: bool = False,
    ) -> str:
        """
        Executes a custom tool (command or script) with template substitution
        and $VAULT: token resolution.
        """
        # Block god_mode tools when god mode is not active
        if tool_def.get("god_mode") and not god_mode_active:
            return (
                f"Tool '{tool_def.get('name')}' requires God Mode to be enabled. "
                "Ask the user to enable God Mode before running destructive operations."
            )

        cmd_template = tool_def.get("command") or tool_def.get("script")
        if not cmd_template:
            return "Error: No command or script defined for this tool."

        # Template substitution: {{ key }} -> params[key]
        cmd = cmd_template
        for k, v in params.items():
            safe_v = _sanitize_template_param(str(v))
            cmd = cmd.replace(f"{{{{ {k} }}}}", safe_v).replace(f"{{{{{k}}}}}", safe_v)

        # Resolve $VAULT: tokens if a cluster context is provided
        if cluster_id and "$VAULT:" in cmd:
            from app.services.vault_resolver import vault_resolver, VaultCredentialNotFound, VaultFieldNotFound
            from app.core.db import AsyncSessionLocal as _ASL
            try:
                async with _ASL() as _db:
                    cmd = await vault_resolver.resolve(cmd, cluster_id, _db)
            except (VaultCredentialNotFound, VaultFieldNotFound) as e:
                return f"Vault error: {e}"

        # Guard: if $VAULT: tokens remain, resolution was skipped (no cluster selected or found)
        if "$VAULT:" in cmd:
            if not cluster_context:
                return (
                    "Vault error: no cluster context selected. "
                    "Use the cluster selector in the top header to choose a cluster, then retry."
                )
            return (
                f"Vault error: cluster '{cluster_context}' was not found in the database — "
                "it may be a local kubeconfig context that hasn't been registered. "
                "Go to Clusters, ensure the cluster is added, then configure its credentials in Vault."
            )

        try:
            execution_env = os.environ.copy()
            from app.services.env_service import env_var_service, PROTECTED_ENV_KEYS
            ui_env_vars = env_var_service.get_all_as_dict()
            safe_ui_vars = {k: v for k, v in ui_env_vars.items() if k not in PROTECTED_ENV_KEYS}
            execution_env.update(safe_ui_vars)

            # For DB clusters, generate a temp kubeconfig so kubectl --context works
            # regardless of what's in the mounted ~/.kube/config.
            _tmp_kubeconfig: Optional[str] = None
            if cluster_id and not cluster_id.startswith("local-"):
                _tmp_kubeconfig = await _build_kubeconfig_for_cluster(cluster_id)
            if _tmp_kubeconfig:
                execution_env["KUBECONFIG"] = _tmp_kubeconfig

            temp_path: Optional[str] = None
            try:
                if tool_def.get("script"):
                    script_content = cmd if cmd.startswith("#!") else f"#!/bin/sh\n{cmd}"
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as tf:
                        tf.write(script_content)
                        temp_path = tf.name

                    if os.name != 'nt':
                        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["bash", temp_path],
                        capture_output=True, text=True, timeout=30, env=execution_env,
                    )
                else:
                    import shlex
                    result = await asyncio.to_thread(
                        subprocess.run, shlex.split(cmd),
                        shell=False, capture_output=True, text=True, timeout=30, env=execution_env,
                    )
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                if _tmp_kubeconfig:
                    try:
                        os.unlink(_tmp_kubeconfig)
                    except OSError:
                        pass

            if result.returncode == 0:
                output = result.stdout or "Success."
                return output[:10000]
            else:
                combined = "\n".join(filter(None, [result.stdout.strip(), result.stderr.strip()]))
                return f"Error ({result.returncode}): {combined or '(no output)'}"
        except Exception as e:
            return f"Execution error: {str(e)}"

    async def _call_model(
        self,
        messages: list,
        tools: list,
        provider: str,
        client,
        model: str,
    ) -> tuple:
        """
        Call the configured AI provider and return (text, tool_calls).
        Exactly one of the two will be non-None.
        """
        if provider == "GEMINI":
            return await self._call_model_gemini(messages, tools, client)
        return await self._call_model_openai(messages, tools, client, model)

    # ── Dynamic tool selection ──────────────────────────────────────────────────

    # Core K8s tools always included for k8s/general queries
    _CORE_K8S = {
        "get_cluster_health", "search_pods", "get_pod_logs", "get_pod_events",
        "describe_pod", "get_deployments", "get_nodes", "get_services",
        "get_namespaces", "get_configmaps", "get_secrets_names",
        "diagnose_pod", "diagnose_service", "search_topology",
        "scale_deployment", "deploy_application", "create_namespace",
        "delete_pod", "get_pod_details", "get_ingresses",
    }

    _DISCOVER_TOOL_SCHEMA = {
        "type": "function",
        "function": {
            "name": "discover_tools",
            "description": (
                "Find additional tools by intent when the tool you need is not in your "
                "current tool list. Returns matching tool names/descriptions; after calling "
                "this, the matched tools become callable on your next step."
            ),
            "parameters": {
                "type": "object",
                "properties": {"intent": {"type": "string", "description": "what you need to do"}},
                "required": ["intent"],
            },
        },
    }

    _OBS_KEYWORDS = {
        "elastic", "elasticsearch", "kibana", "index", "indices", "logstash",
        "prometheus", "grafana", "loki", "datadog", "metric", "metrics",
        "log", "logs", "search", "query", "trace", "span", "apm",
    }
    _MINION_KEYWORDS = {
        "minion", "on-prem", "on-premise", "edge", "device", "salt",
    }
    _WRITE_KEYWORDS = {
        "scale", "deploy", "create", "delete", "patch", "restart",
        "rollout", "upgrade", "apply", "update", "fix", "install",
    }
    # Maps query keywords → tool name prefixes for service tools
    _SERVICE_TOOL_MAP = {
        "rabbitmq":  "rabbitmq_",
        "rabbit":    "rabbitmq_",
        "queue":     "rabbitmq_",
        "queues":    "rabbitmq_",
        "vhost":     "rabbitmq_",
        "amqp":      "rabbitmq_",
        "exchange":  "rabbitmq_",
        "binding":   "rabbitmq_",
        "redis":     "redis_",
        "cache":     "redis_",
        "keyspace":  "redis_",
        "postgres":  "postgres_",
        "postgresql":"postgres_",
        "psql":      "postgres_",
        "mysql":     "mysql_",
        "mariadb":   "mysql_",
        "innodb":    "mysql_",
        "mongodb":   "mongo_",
        "mongo":     "mongo_",
        "couchdb":   "couchdb_",
        "couch":     "couchdb_",
        "mssql":              "mssql_",
        "sqlserver":          "mssql_",
        "sql server":         "mssql_",
        "registry":           "registry_",
        "acr":                "registry_",
        "ecr":                "registry_",
        "harbor":             "registry_",
        "container registry": "registry_",
        "image tag":          "registry_",
        "imagepullbackoff":   "registry_",
        "errimagepull":       "registry_",
        "image pull":         "registry_",
    }

    @staticmethod
    def _score_tool(query_words: set[str], tool: dict) -> int:
        """Relevance score = count of query words (len > 3) found in name+description."""
        fn = tool["function"]
        haystack = (fn["name"] + " " + fn.get("description", "")).lower()
        return sum(1 for w in query_words if len(w) > 3 and w in haystack)

    @staticmethod
    def _select_dynamic_tools(
        query: str,
        obs_tools_schema: list,
        full_k8s_schema: list,
        mcp_schema: list,
        custom_tools_schema: list,
        max_total: int = 64,
        min_score: int = 1,
        history: Optional[list] = None,
    ) -> list:
        q = query.lower()

        is_obs      = any(kw in q for kw in AIService._OBS_KEYWORDS)
        is_minion   = any(kw in q for kw in AIService._MINION_KEYWORDS)
        is_write    = any(kw in q for kw in AIService._WRITE_KEYWORDS)
        is_diagnose = any(kw in q for kw in ("what's wrong", "not working", "failing", "broken",
                                              "investigate", "issue", "error", "crash", "debug",
                                              "troubleshoot", "why", "check"))

        # Detect which service tool prefixes are relevant to this query
        matched_service_prefixes: set = set()
        for kw, prefix in AIService._SERVICE_TOOL_MAP.items():
            if kw in q:
                matched_service_prefixes.add(prefix)

        # If no service keyword in current message, scan recent history so follow-up
        # messages ("now show slow queries") retain the same service tools.
        # Check both message text AND previous tool call names (e.g. rabbitmq_list_queues).
        if not matched_service_prefixes and history:
            recent_msgs = history[-8:]
            # Collect all text: message content + tool call function names
            text_parts: list = []
            for m in recent_msgs:
                content = m.get("content", "")
                if isinstance(content, str):
                    text_parts.append(content)
                # Tool call names in assistant messages
                for tc in m.get("tool_calls", []) or []:
                    fn_name = ""
                    if isinstance(tc, dict):
                        fn_name = tc.get("function", {}).get("name", "")
                    elif hasattr(tc, "function"):
                        fn_name = getattr(tc.function, "name", "")
                    if fn_name:
                        text_parts.append(fn_name)
            recent_text = " ".join(text_parts).lower()
            for kw, prefix in AIService._SERVICE_TOOL_MAP.items():
                if kw in recent_text:
                    matched_service_prefixes.add(prefix)
            # Also match by tool name prefix directly (catches tool results like source="rabbitmq")
            _all_svc_prefixes = set(AIService._SERVICE_TOOL_MAP.values())
            for pfx in _all_svc_prefixes:
                short = pfx.rstrip("_")  # e.g. "rabbitmq_" → "rabbitmq"
                if short in recent_text:
                    matched_service_prefixes.add(pfx)

        is_service  = bool(matched_service_prefixes)

        selected: list = []

        # Obs tools first for obs queries OR diagnostic queries (AI should cross-reference ES logs)
        if is_obs or is_diagnose:
            selected.extend(obs_tools_schema)

        # Service tools: inject ALL tools for matched service(s) when a service keyword is detected
        if is_service:
            for t in full_k8s_schema:
                fn_name = t["function"]["name"]
                if any(fn_name.startswith(pfx) for pfx in matched_service_prefixes):
                    selected.append(t)

        # K8s tools: core always (unless pure service query), extras only when write intent or not obs-only
        k8s_core    = [t for t in full_k8s_schema if t["function"]["name"] in AIService._CORE_K8S]
        k8s_minion  = [t for t in full_k8s_schema if "minion" in t["function"]["name"]]
        k8s_write   = [t for t in full_k8s_schema if t["function"]["name"] not in AIService._CORE_K8S
                       and "minion" not in t["function"]["name"]
                       and any(w in t["function"]["name"] for w in ("scale", "deploy", "delete", "create", "patch", "apply", "restart"))]
        # k8s_rest excludes service tools (they have their own selection path above)
        _all_service_prefixes = set(AIService._SERVICE_TOOL_MAP.values())
        k8s_rest    = [t for t in full_k8s_schema if t["function"]["name"] not in AIService._CORE_K8S
                       and "minion" not in t["function"]["name"]
                       and t not in k8s_write
                       and not any(t["function"]["name"].startswith(pfx) for pfx in _all_service_prefixes)]

        if is_minion:
            selected.extend(k8s_minion)
        elif not is_service:
            # Pure k8s query path
            selected.extend(k8s_core)
            if is_write:
                selected.extend(k8s_write)
            if not is_obs:
                # Relevance-ranked rest: include every tool that matches the query,
                # not an arbitrary first-15 slice.
                qwords = set(q.split())
                scored_rest = sorted(
                    ((AIService._score_tool(qwords, t), t) for t in k8s_rest),
                    key=lambda pair: pair[0], reverse=True,
                )
                selected.extend(t for score, t in scored_rest if score >= min_score)
        else:
            # Service query: still include core k8s for context but skip the long k8s_rest tail
            selected.extend(k8s_core)
            if is_write:
                selected.extend(k8s_write)

        # Custom tools: only include if any keyword from query matches tool name/description
        query_words = set(q.split())
        for ct in custom_tools_schema:
            fn = ct["function"]
            combined = (fn["name"] + " " + fn.get("description", "")).lower()
            if any(w in combined for w in query_words if len(w) > 3):
                selected.append(ct)

        # MCP tools always included (usually small set)
        selected.extend(mcp_schema)

        # Obs tools at end even for non-obs queries (model can still use them)
        if not is_obs:
            selected.extend(obs_tools_schema)

        # Deduplicate by tool name while preserving order
        seen: set = set()
        deduped: list = []
        for t in selected:
            name = t["function"]["name"]
            if name not in seen:
                seen.add(name)
                deduped.append(t)

        import logging as _tl
        _tl.getLogger("ai_service.tools").debug(
            "[TOOLS] dynamic selection: obs=%d core_k8s=%d write=%d minion=%d custom_matched=%d mcp=%d → total=%d (was %d)",
            len(obs_tools_schema),
            len([t for t in deduped if t["function"]["name"] in AIService._CORE_K8S]),
            len([t for t in deduped if t in k8s_write]),
            len([t for t in deduped if "minion" in t["function"]["name"]]),
            len([t for t in deduped if t in custom_tools_schema]),
            len(mcp_schema),
            len(deduped),
            len(obs_tools_schema) + len(full_k8s_schema) + len(mcp_schema) + len(custom_tools_schema),
        )

        if not any(t["function"]["name"] == "discover_tools" for t in deduped):
            deduped.append(AIService._DISCOVER_TOOL_SCHEMA)

        if len(deduped) <= max_total:
            return deduped
        qwords = set(q.split())
        # Keep core tools unconditionally; rank the remainder by relevance.
        core = [t for t in deduped if t["function"]["name"] in AIService._CORE_K8S]
        rest = [t for t in deduped if t["function"]["name"] not in AIService._CORE_K8S]
        rest.sort(key=lambda t: AIService._score_tool(qwords, t), reverse=True)
        return (core + rest)[:max_total]

    @staticmethod
    def _strip_tool_echo(text: str) -> str:
        """Remove 'to=toolname <garbage>' prefixes some non-standard models emit."""
        if not text or "to=" not in text:
            return text
        # Strip one or more "to=<word> <any chars>" blocks that precede the real response
        cleaned = re.sub(r'(?:to=\w+\s+[^\n]*\n*)+', '', text, flags=re.DOTALL).strip()
        return cleaned if cleaned else text.strip()

    async def _call_model_openai(self, messages: list, tools: list, client, model: str) -> tuple:
        import logging as _logging
        _model_log = _logging.getLogger("ai_service.model")
        try:
            kwargs: dict = {"model": model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            _model_log.debug("[MODEL] calling model=%s messages=%d tools=%d", model, len(messages), len(tools))
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
            msg = response.choices[0].message
            if msg.tool_calls:
                _model_log.debug("[MODEL] response: tool_calls=%s", [tc.function.name for tc in msg.tool_calls])
                return None, msg.tool_calls
            raw_content = msg.content or ""
            cleaned = self._strip_tool_echo(raw_content)
            _model_log.debug("[MODEL] response raw[:300]: %s", raw_content[:300])
            if cleaned != raw_content:
                _model_log.debug("[MODEL] stripped tool echo prefix. cleaned[:300]: %s", cleaned[:300])
            return cleaned, None
        except Exception as e:
            err_lower = str(e).lower()
            _model_log.debug("[MODEL] exception: %s", str(e)[:300])
            if tools and ("tool" in err_lower or "function" in err_lower or "context" in err_lower or "token" in err_lower or "length" in err_lower):
                _model_log.debug("[MODEL] retrying without tools due to: %s", str(e)[:200])
                response = await asyncio.to_thread(client.chat.completions.create, model=model, messages=messages)
                content = self._strip_tool_echo(response.choices[0].message.content or "")
                _model_log.debug("[MODEL] no-tools retry response[:200]: %s", content[:200])
                return content, None
            raise

    async def _call_model_gemini(self, messages: list, tools: list, client) -> tuple:
        import json
        from types import SimpleNamespace
        from app.tools.registry import build_gemini_tools_schema

        gemini_tools = build_gemini_tools_schema()
        text_prompt = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')}"
            for m in messages
            if m.get("content")
        )
        try:
            response = await asyncio.to_thread(client.generate_content, text_prompt, tools=gemini_tools)
            normalized_calls = []
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    normalized_calls.append(SimpleNamespace(
                        id=f"gemini_{fc.name}",
                        function=SimpleNamespace(
                            name=fc.name,
                            arguments=json.dumps(dict(fc.args)),
                        ),
                    ))
            if normalized_calls:
                return None, normalized_calls
            return response.text, None
        except Exception:
            # Gemini tool calling failed — fall back to plain text
            response = await asyncio.to_thread(client.generate_content, text_prompt)
            return response.text, None

    async def run_agentic_loop(
        self,
        namespace: str,
        pod_name: str,
        query: str,
        context: Optional[str] = None,
        runbook_id: Optional[str] = None,
        evidence_context: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        from app.services.k8s_service import k8s_service
        from app.services.runbook_service import runbook_service
        try:
            caching_client = self._get_caching_client()
            yield {"type": "model", "message": caching_client.full_model}
            provider = self._get_setting("ai_provider")

            # Resolve cluster_id from context name for vault credential lookups.
            # DB clusters have UUID IDs; local kubeconfig-only clusters get synthetic
            # "local-<name>" IDs (see list_clusters in clusters.py) — fall back to
            # that format so vault credentials saved against local clusters still resolve.
            cluster_id: Optional[str] = None
            if context:
                from sqlmodel import select
                from app.core.db import AsyncSessionLocal as _ASL
                from app.models.cluster import ClusterConnection
                async with _ASL() as _cdb:
                    cluster = (await _cdb.exec(
                        select(ClusterConnection).where(ClusterConnection.name == context)
                    )).first()
                    if cluster:
                        cluster_id = cluster.id
                    else:
                        cluster_id = f"local-{context}"

            # Resolve god_mode status for this user
            from app.core.god_mode import is_god_mode_active
            god_mode_active = is_god_mode_active(user_id) if user_id else False

            custom_tools = self._get_custom_tools_definitions()
            from app.tools import registry as _registry

            if provider == "GEMINI":
                tools_schema = _registry.build_gemini_tools_schema(extra_tools=custom_tools)
            else:
                tools_schema = _registry.build_openai_tools_schema(extra_tools=custom_tools)

            evidence_section = ""
            if evidence_context:
                evidence_section = f"\n\nPRE-COLLECTED EVIDENCE (gathered before this RCA — treat as ground truth):\n{evidence_context[:3000]}\n"

            system_prompt = f"""{_GLOBAL_AGENT_STATIC_SYSTEM}

TARGET POD: {namespace}/{pod_name}
User Query: {query}
{evidence_section}
Available tools: get_logs, get_events, describe_pod (all scoped to the target pod above).
Use the pre-collected evidence above if provided. Use tools for additional investigation if needed.
When you have enough evidence, give your final answer directly — do NOT call any more tools.
"""
            messages: list = [{"role": "system", "content": system_prompt}]
            messages.append({"role": "user", "content": query})

            # Runbook pre-execution
            if runbook_id:
                rb = runbook_service.get_runbook(runbook_id)
                if rb:
                    yield {"type": "step", "message": f"Runbook: {rb.get('name', runbook_id)}..."}
                    for rb_step in rb.get("steps", []):
                        tool_name = rb_step.get("tool")
                        step_name = rb_step.get("name")
                        yield {"type": "step", "message": f"Runbook step: {step_name}..."}
                        obs = ""
                        try:
                            if tool_name == "get_logs":
                                obs = await k8s_service.get_pod_logs(namespace, pod_name, tail_lines=200, context=context)
                            elif tool_name == "get_events":
                                obs = await k8s_service.get_pod_events(namespace, pod_name, context=context)
                            elif tool_name == "describe_pod":
                                obs = await k8s_service.get_pod_details(namespace, pod_name, context=context)
                        except Exception as e:
                            obs = f"Error: {e}"
                        messages.append({"role": "user", "content": f"Runbook observation ({step_name}):\n{obs}"})

            max_steps = 5
            current_step = 0
            use_react_fallback = False

            while current_step < max_steps:
                current_step += 1
                text, tool_calls = await caching_client.complete(
                    messages,
                    tools_schema,
                    tier="full",
                    disable_trimming=False,
                    trim_keep=4,
                    trim_token_cap=8000,
                )

                if current_step == 1 and text is not None and not tool_calls and tools_schema:
                    use_react_fallback = True

                if use_react_fallback:
                    if not text:
                        yield {"type": "result", "message": "AI returned empty response."}
                        return
                    if "Final Answer:" in text:
                        yield {"type": "result", "message": text[text.find("Final Answer:") + len("Final Answer:"):].strip()}
                        return
                    if "Action:" in text:
                        action_lines = [l for l in text.splitlines() if l.startswith("Action:")]
                        if not action_lines:
                            yield {"type": "result", "message": text}
                            return
                        action = action_lines[0].replace("Action:", "").strip()
                        yield {"type": "step", "message": f"{action}..."}
                        obs = ""
                        if action == "get_logs":
                            obs = sanitize_for_llm(await k8s_service.get_pod_logs(namespace, pod_name, tail_lines=200, context=context))
                        elif action == "get_events":
                            obs = sanitize_for_llm(await k8s_service.get_pod_events(namespace, pod_name, context=context))
                        elif action == "describe_pod":
                            obs = sanitize_for_llm(await k8s_service.get_pod_details(namespace, pod_name, context=context))
                        else:
                            custom_tool = next((t for t in custom_tools if t["name"] == action), None)
                            if custom_tool:
                                obs = sanitize_for_llm(await self._execute_custom_tool(
                                    custom_tool,
                                    {"namespace": namespace, "pod_name": pod_name},
                                    cluster_id=cluster_id,
                                    cluster_context=context,
                                    god_mode_active=god_mode_active,
                                ))
                            else:
                                obs = f"Tool {action} not found."
                        yield {"type": "step", "message": f"{action} done."}
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content": f"Observation:\n{obs}\n\nNext Action or Final Answer?"})
                    else:
                        yield {"type": "result", "message": text}
                        return
                    continue

                if tool_calls:
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in tool_calls
                        ],
                    })
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        yield {"type": "step", "message": f"{tool_name}..."}
                        obs = ""
                        try:
                            if tool_name == "get_logs":
                                obs = sanitize_for_llm(await k8s_service.get_pod_logs(namespace, pod_name, tail_lines=200, context=context))
                            elif tool_name == "get_events":
                                obs = sanitize_for_llm(await k8s_service.get_pod_events(namespace, pod_name, context=context))
                            elif tool_name == "describe_pod":
                                obs = sanitize_for_llm(await k8s_service.get_pod_details(namespace, pod_name, context=context))
                            else:
                                custom_tool = next((t for t in custom_tools if t["name"] == tool_name), None)
                                if custom_tool:
                                    try:
                                        tool_inputs = json.loads(tc.function.arguments)
                                    except Exception:
                                        tool_inputs = {}
                                    obs = sanitize_for_llm(await self._execute_custom_tool(
                                        custom_tool,
                                        {**tool_inputs, "namespace": namespace, "pod_name": pod_name},
                                        cluster_id=cluster_id,
                                        cluster_context=context,
                                        god_mode_active=god_mode_active,
                                    ))
                                else:
                                    obs = f"Tool {tool_name} not found."
                        except Exception as e:
                            obs = f"Error: {e}"
                        yield {"type": "step", "message": f"{tool_name} done."}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": obs})
                else:
                    yield {"type": "result", "message": text or ""}
                    return

            yield {"type": "result", "message": "Agent reached max iterations without a final answer."}
        except Exception as e:
            yield {"type": "result", "message": f"Agent error: {str(e)}"}

    async def run_batch_agentic_loop(
        self,
        pods: list,
        query: str,
        context=None,
        runbook_id: str | None = None,
    ):
        from app.services.k8s_service import k8s_service
        from app.services.runbook_service import runbook_service
        try:
            caching_client = self._get_caching_client()
            yield {"type": "model", "message": caching_client.full_model}
            provider = self._get_setting("ai_provider")

            custom_tools = self._get_custom_tools_definitions()
            from app.tools import registry as _registry

            target_pods_str = ", ".join(f"{p['namespace']}/{p['pod_name']}" for p in pods)

            if provider == "GEMINI":
                tools_schema = _registry.build_gemini_tools_schema(extra_tools=custom_tools)
            else:
                tools_schema = _registry.build_openai_tools_schema(extra_tools=custom_tools)

            system_prompt = f"""{_GLOBAL_AGENT_STATIC_SYSTEM}

TARGET PODS: {target_pods_str}
User Query: {query}

Use get_pod_logs, get_pod_events, or describe_pod with the correct namespace/pod_name to investigate each pod.
When done, give a per-pod root cause analysis.
"""
            messages: list = [{"role": "system", "content": system_prompt}]
            messages.append({"role": "user", "content": query})

            # Runbook pre-execution for all pods
            if runbook_id:
                rb = runbook_service.get_runbook(runbook_id)
                if rb:
                    yield {"type": "step", "message": f"Batch Runbook: {rb.get('name', runbook_id)}..."}
                    for pod in pods:
                        ns, p_name = pod["namespace"], pod["pod_name"]
                        for rb_step in rb.get("steps", []):
                            tool_name = rb_step.get("tool")
                            step_name = rb_step.get("name")
                            yield {"type": "step", "message": f"Runbook ({p_name}): {step_name}..."}
                            obs = ""
                            try:
                                if tool_name in ["get_logs", "get_pod_logs"]:
                                    obs = await k8s_service.get_pod_logs(ns, p_name, tail_lines=200, context=context)
                                elif tool_name in ["get_events", "get_pod_events"]:
                                    obs = await k8s_service.get_pod_events(ns, p_name, context=context)
                                elif tool_name in ["describe_pod", "get_pod_status"]:
                                    obs = await k8s_service.get_pod_details(ns, p_name, context=context)
                            except Exception as e:
                                obs = f"Error: {e}"
                            messages.append({"role": "user", "content": f"Runbook ({p_name} / {step_name}):\n{obs}"})

            max_steps = 7
            current_step = 0
            use_react_fallback = False

            while current_step < max_steps:
                current_step += 1
                text, tool_calls = await caching_client.complete(
                    messages,
                    tools_schema,
                    tier="full",
                    disable_trimming=False,
                    trim_keep=6,
                    trim_token_cap=10000,
                )

                if current_step == 1 and text is not None and not tool_calls and tools_schema:
                    use_react_fallback = True

                if use_react_fallback:
                    if not text:
                        yield {"type": "result", "message": "AI returned empty response."}
                        return
                    if "Final Answer:" in text:
                        yield {"type": "result", "message": text[text.find("Final Answer:") + len("Final Answer:"):].strip()}
                        return
                    if "Action:" in text:
                        action_lines = [l for l in text.splitlines() if l.startswith("Action:")]
                        if not action_lines:
                            yield {"type": "result", "message": text}
                            return
                        action = action_lines[0].replace("Action:", "").strip(" []'\"")
                        input_lines = [l for l in text.splitlines() if l.startswith("Action Input:")]
                        action_input = input_lines[0].replace("Action Input:", "").strip() if input_lines else ""
                        yield {"type": "step", "message": f"{action}..."}
                        obs = ""
                        if "/" in action_input:
                            ns, p_name = action_input.split("/", 1)
                            if action in ["get_logs", "get_pod_logs"]:
                                obs = sanitize_for_llm(await k8s_service.get_pod_logs(ns, p_name, tail_lines=200, context=context))
                            elif action in ["get_events", "get_pod_events"]:
                                obs = sanitize_for_llm(await k8s_service.get_pod_events(ns, p_name, context=context))
                            elif action in ["describe_pod", "get_pod_status"]:
                                obs = sanitize_for_llm(await k8s_service.get_pod_details(ns, p_name, context=context))
                        else:
                            obs = "Invalid Action Input. Expected namespace/pod_name."
                        yield {"type": "step", "message": f"{action} done."}
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content": f"Observation:\n{obs}\n\nNext Action or Final Answer?"})
                    else:
                        yield {"type": "result", "message": text}
                        return
                    continue

                if tool_calls:
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in tool_calls
                        ],
                    })
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        try:
                            tool_inputs = json.loads(tc.function.arguments)
                        except Exception:
                            tool_inputs = {}
                        yield {"type": "step", "message": f"{tool_name}..."}
                        exec_res = await _registry.execute_tool_async(tool_name, tool_inputs)
                        if isinstance(exec_res, dict) and exec_res.get("requires_confirmation"):
                            pending_op_data = exec_res.get("pending_operation", {})
                            op_id = str(uuid.uuid4())
                            new_op = {
                                "id": op_id,
                                "session_id": "global_session",
                                "tool_name": tool_name,
                                "tool_inputs": tool_inputs,
                                "confirmation_message": pending_op_data.get("confirmation_message") or exec_res.get("confirmation_message"),
                                "risk_level": pending_op_data.get("risk_level") or exec_res.get("risk_level", "medium"),
                                "created_at": time.time(),
                                "status": "pending",
                                "executed_at": None,
                                "result": None,
                            }
                            from app.api.v1.operations import pending_operations_store
                            pending_operations_store[op_id] = new_op
                            yield {"type": "pending_operation", "message": new_op["confirmation_message"], "operation": new_op}
                            return
                        observation = sanitize_for_llm(str(exec_res))
                        yield {"type": "step", "message": f"{tool_name} done."}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                else:
                    yield {"type": "result", "message": text or ""}
                    return

            yield {"type": "result", "message": "Agent reached max iterations without a final answer."}
        except Exception as e:
            yield {"type": "result", "message": f"Agent error: {str(e)}"}

    async def run_global_agentic_loop(
        self,
        query: str,
        context=None,
        runbook_id: str | None = None,
        history: list | None = None,
        workflow_tools_schema: list | None = None,
        workflow_tool_executors: dict | None = None,
        evidence_context: Optional[str] = None,
        disable_trimming: bool = False,
    ):
        from app.services.k8s_service import active_cluster_ctx
        ctx_token = active_cluster_ctx.set(context) if context else None
        try:
            async for event in self._run_global_agentic_loop_inner(
                query=query,
                context=context,
                runbook_id=runbook_id,
                history=history,
                workflow_tools_schema=workflow_tools_schema,
                workflow_tool_executors=workflow_tool_executors,
                evidence_context=evidence_context,
                disable_trimming=disable_trimming,
            ):
                yield event
        finally:
            if ctx_token is not None:
                active_cluster_ctx.reset(ctx_token)

    async def _run_global_agentic_loop_inner(
        self,
        query: str,
        context=None,
        runbook_id: str | None = None,
        history: list | None = None,
        workflow_tools_schema: list | None = None,
        workflow_tool_executors: dict | None = None,
        evidence_context: Optional[str] = None,
        disable_trimming: bool = False,
    ):
        try:
            caching_client = self._get_caching_client()
            yield {"type": "model", "message": caching_client.full_model}
            yield {"type": "step", "message": "Thinking..."}
            _agent_log.info("[AGENT] loop start — model=%s query_preview=%.120s", caching_client.full_model, query)

            investigation_mode = await self.classify_investigation(query, caching_client)
            _agent_log.info("[AGENT] investigation_mode=%s", investigation_mode)

            _prereq_warnings, _unhealthy_int_names, _unavailability_block = await self._run_prerequisite_check()
            for _ev in _prereq_warnings:
                yield _ev

            provider = self._get_setting("ai_provider")
            _agent_log.info("[AGENT] provider=%s", provider)

            custom_tools = self._get_custom_tools_definitions()
            rag_enabled = (self._get_setting("rag_enabled") or "false").lower() == "true"
            _agent_log.info("[AGENT] rag_enabled=%s custom_tools=%d", rag_enabled, len(custom_tools or []))

            rag_section = ""
            if rag_enabled:
                try:
                    from app.services.rag_service import rag_service as _rag
                    kb_hits = await _rag.retrieve(query, "knowledge_base", n_results=3)
                    incident_hits = await _rag.retrieve(query, "incidents", n_results=5)
                    combined = "\n\n".join(
                        part for part in [kb_hits, incident_hits]
                        if part and "No relevant documents found" not in part and "unavailable" not in part
                    )
                    if combined:
                        rag_section = f"\n\nKNOWLEDGE BASE CONTEXT (retrieved from indexed documents — treat as authoritative):\n{combined}\n"
                        _agent_log.info("[AGENT] RAG injected %d chars", len(rag_section))
                except Exception as _rag_err:
                    _agent_log.warning("[AGENT] RAG retrieval failed: %s", _rag_err)

            # External knowledge sources — queried independently of internal RAG toggle
            try:
                from app.services.external_rag_service import external_rag_service
                ext_hits = await external_rag_service.retrieve_all(query)
                if ext_hits:
                    rag_section += f"\n\nEXTERNAL KNOWLEDGE SOURCE CONTEXT (retrieved from company knowledge base — treat as authoritative):\n{ext_hits}\n"
                    _agent_log.info("[AGENT] External RAG injected %d chars", len(ext_hits))
            except Exception as _ext_err:
                _agent_log.warning("[AGENT] External RAG retrieval failed: %s", _ext_err)

            # Resolve cluster_id for $VAULT: token resolution in custom tool scripts.
            # DB clusters have UUID IDs; local kubeconfig-only clusters get synthetic
            # "local-<name>" IDs (see list_clusters) — fall back to that format.
            cluster_id: Optional[str] = None
            if context:
                from sqlmodel import select
                from app.core.db import AsyncSessionLocal as _ASL
                from app.models.cluster import ClusterConnection
                async with _ASL() as _cdb:
                    _cluster = (await _cdb.exec(
                        select(ClusterConnection).where(ClusterConnection.name == context)
                    )).first()
                    cluster_id = _cluster.id if _cluster else f"local-{context}"

            # god_mode not available here (no user_id); destructive toolset scripts blocked by default.
            god_mode_active: bool = False

            from app.tools import registry as _registry
            from app.services.mcp_client_service import mcp_client_service as _mcp_svc
            from app.services.integration_manager import integration_manager as _int_mgr
            from app.services.context_manager import context_manager as _ctx_mgr
            _agent_log.info("[AGENT] loading obs tool registry...")
            _obs_registry_raw = _int_mgr.get_active_tool_registry()
            _obs_registry = {
                name: tool for name, tool in _obs_registry_raw.items()
                if not any(name.startswith(p) for p in _unhealthy_int_names)
            }
            _obs_extra = [{"name": n, "description": i["description"], "inputs": i.get("inputs", [])} for n, i in _obs_registry.items()]
            _obs_prompt = _int_mgr.get_tools_description_for_prompt(registry=_obs_registry)
            _agent_log.info("[AGENT] obs tools loaded: %d", len(_obs_registry))

            if provider == "GEMINI":
                tools_schema = _registry.build_gemini_tools_schema(extra_tools=(custom_tools or []) + _obs_extra)
                mcp_declarations = await _mcp_svc.build_gemini_tools_schema()
                if mcp_declarations:
                    tools_schema[0]["function_declarations"].extend(mcp_declarations)
            else:
                # Build each group separately then apply dynamic selection
                _obs_tools_schema = [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": {
                                "type": "object",
                                "properties": {i: {"type": "string", "description": i} for i in t.get("inputs", [])},
                                "required": [],
                            },
                        },
                    }
                    for t in _obs_extra
                ]
                _full_k8s_schema = _registry.build_openai_tools_schema()
                _custom_schema = _registry.build_openai_tools_schema(extra_tools=custom_tools or [])[len(_full_k8s_schema):]
                _mcp_schema = await _mcp_svc.build_openai_tools_schema()

                tools_schema = self._select_dynamic_tools(
                    query, _obs_tools_schema, _full_k8s_schema, _mcp_schema, _custom_schema,
                    history=history,
                )
                if workflow_tools_schema:
                    tools_schema.extend(workflow_tools_schema)

            _agent_log.info("[AGENT] tools_schema built: %d tools", len(tools_schema))

            mcp_tools_prompt = await _mcp_svc.get_all_tools_for_prompt()
            mcp_section = f"{mcp_tools_prompt}\n\nMCP TOOL RULE: When the user asks about systems managed by an external MCP server (e.g. Uyuni, Jira, GitHub), prefer mcp__ prefixed tools over Kubernetes tools.\n\n" if mcp_tools_prompt else ""

            runbook_instruction = ""
            if runbook_id:
                from app.services.runbook_service import runbook_service
                rb = runbook_service.get_runbook(runbook_id)
                if rb:
                    runbook_instruction = f"\n\n--- RUNBOOK: {rb['name']} ---\n{rb['body']}\n\nFollow these instructions exactly."

            from app.services.topology_service import topology_service
            from app.services.k8s_service import k8s_service
            _topo_ctx = context or k8s_service.default_context
            _agent_log.info("[AGENT] getting topology overview for context=%s", _topo_ctx)
            _topo_overview = topology_service.get_cluster_overview(_topo_ctx)
            _agent_log.info("[AGENT] topology done, building system prompt...")

            evidence_section = ""
            if evidence_context:
                evidence_section = f"\n\nPRE-COLLECTED EVIDENCE:\n{evidence_context[:3000]}\n"

            obs_section = ""
            if _obs_prompt:
                obs_section = f"""OBSERVABILITY ROUTING — when the user asks about logs, metrics, indices, Elasticsearch, Prometheus, Loki, Grafana, or Datadog: use the observability tools below FIRST. Do NOT use Kubernetes tools for these queries. IMPORTANT: if a tool returns 0 results or an error, report that exact result — do NOT invent log entries, index names, or metrics data.

ELASTICSEARCH QUERY RULES:
- NEVER skip searching just because elasticsearch_list_indices returned empty — proceed to elasticsearch_search anyway.
- USE query_string AS THE DEFAULT query type — it matches exactly what Kibana KQL does and handles field types automatically.
- ECS kubernetes fields are keyword type — NO .keyword suffix needed:
  kubernetes.namespace, kubernetes.pod.name, kubernetes.container.name, kubernetes.node.name
- query_string examples (mirror Kibana KQL syntax):
  Namespace wildcard:  {{"query_string":{{"query":"kubernetes.namespace:*uat34*"}}}}
  Pod + namespace:     {{"query_string":{{"query":"kubernetes.pod.name:*payments-api* AND kubernetes.namespace:*uat34*"}}}}
  Full text in logs:   {{"query_string":{{"query":"error OR exception","default_field":"message"}}}}
  With time range:     combine query_string in bool.must with range on @timestamp
- CRITICAL: when the user says "pod name is X" or "service is X" or "app is X", ALWAYS put it as a FIELD filter: kubernetes.pod.name:*X* — NEVER as a bare term or default_field search.
- Do NOT add a time range filter unless the user explicitly asked for one.
- If 0 results: 1) call elasticsearch_resolve_index on the pattern to see what indices it actually expands to, 2) retry WITHOUT time range, 3) call elasticsearch_get_mapping to verify field names, 4) try broader index pattern like '*'.
- search always uses expand_wildcards=open,hidden so data stream backing indices are included.
{_obs_prompt}

"""

            _core_prompt = build_agent_system_prompt(investigation=investigation_mode, selected_tools=tools_schema)
            dynamic_context = f"""{_core_prompt}{_unavailability_block}

CLUSTER TOPOLOGY SNAPSHOT:
{_topo_overview}

{obs_section}{mcp_section}User Query: {query}
{runbook_instruction}{evidence_section}{rag_section}"""

            messages: list = [{"role": "system", "content": dynamic_context}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": query})

            max_steps = 30 if investigation_mode else 15
            current_step = 0
            use_react_fallback = False
            _agent_log.info("[AGENT] entering loop max_steps=%d messages=%d tools=%d", max_steps, len(messages), len(tools_schema))

            while current_step < max_steps:
                current_step += 1
                _agent_log.info("[AGENT] step %d/%d — calling AI...", current_step, max_steps)

                # Budget check — compact if approaching context limit
                _used, _limit, _pct = _ctx_mgr.check_budget(messages, provider)
                _compact_threshold = float(self._get_setting("ctx_compaction_threshold") or "70") / 100
                if _pct >= _compact_threshold:
                    _agent_log.info("[AGENT] context at %.0f%% — compacting", _pct * 100)
                    messages, _summary = await _ctx_mgr.compact_conversation(
                        messages, provider, caching_client
                    )
                    if _summary:
                        _after_used, _, _ = _ctx_mgr.check_budget(messages, provider)
                        yield {
                            "type": "compaction_banner",
                            "message": (
                                f"Context compacted. Tokens before: {_used:,} · "
                                f"After: {_after_used:,} · Saved: {_used - _after_used:,}"
                            ),
                        }

                text, tool_calls = await caching_client.complete(
                    messages,
                    tools_schema,
                    tier="full",
                    disable_trimming=disable_trimming,
                    trim_keep=10,
                    trim_token_cap=16000,
                )
                _agent_log.info("[AGENT] step %d — AI returned: text_len=%s tool_calls=%s",
                                current_step, len(text) if text else 0, len(tool_calls) if tool_calls else 0)

                # Fallback: first turn, tools provided, only text returned → model doesn't support tool calling
                if current_step == 1 and text is not None and not tool_calls and tools_schema:
                    use_react_fallback = True

                if use_react_fallback:
                    # Legacy ReAct parsing path
                    if not text:
                        yield {"type": "result", "message": "AI returned empty response."}
                        return
                    if "Final Answer:" in text:
                        analysis = text[text.find("Final Answer:") + len("Final Answer:"):].strip()
                        yield {"type": "result", "message": analysis}
                        return
                    if "Action:" in text:
                        action_lines = [l for l in text.splitlines() if l.startswith("Action:")]
                        if not action_lines:
                            yield {"type": "result", "message": text}
                            return
                        action = action_lines[0].replace("Action:", "").strip(" []'\"")
                        input_lines = [l for l in text.splitlines() if l.startswith("Action Input:")]
                        action_input = input_lines[0].replace("Action Input:", "").strip(" []'\"") if input_lines else ""
                        yield {"type": "step", "message": f"{action}..."}
                        try:
                            tool_inputs = json.loads(action_input) if action_input.startswith("{") else {"query": action_input}
                        except Exception:
                            tool_inputs = {"query": action_input}
                        exec_res = await _registry.execute_tool_async(action, tool_inputs)
                        observation = sanitize_for_llm(str(exec_res))
                        yield {"type": "step", "message": f"{action} done."}
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content": f"Observation:\n{observation}\n\nWhat is your next Action or Final Answer?"})
                    else:
                        yield {"type": "result", "message": text}
                        return
                    continue

                if tool_calls:
                    # Append assistant turn with tool_calls BEFORE tool results
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    })

                    for tc in tool_calls:
                        tool_name = tc.function.name
                        try:
                            tool_inputs = json.loads(tc.function.arguments)
                        except Exception:
                            tool_inputs = {}

                        yield {"type": "step", "message": f"{tool_name}..."}

                        observation = ""
                        if rag_enabled and tool_name in _registry.RAG_TOOL_REGISTRY:
                            rag_result = await _registry.execute_rag_tool(tool_name, tool_inputs)
                            observation = sanitize_for_llm(str(rag_result.get("data") or rag_result.get("error") or "No results."))
                        elif tool_name.startswith("mcp__"):
                            exec_res = await _mcp_svc.execute_tool(tool_name, tool_inputs)
                            if isinstance(exec_res, dict) and exec_res.get("requires_confirmation"):
                                pending_op_data = exec_res.get("pending_operation", {})
                                op_id = str(uuid.uuid4())
                                new_op = {
                                    "id": op_id,
                                    "session_id": "global_session",
                                    "tool_name": tool_name,
                                    "tool_inputs": tool_inputs,
                                    "confirmation_message": pending_op_data.get("confirmation_message") or exec_res.get("confirmation_message"),
                                    "risk_level": pending_op_data.get("risk_level") or exec_res.get("risk_level"),
                                    "created_at": time.time(),
                                    "status": "pending",
                                    "executed_at": None,
                                    "result": None,
                                }
                                from app.api.v1.operations import pending_operations_store
                                pending_operations_store[op_id] = new_op
                                _approval_event = asyncio.Event()
                                _pending_approval_events[op_id] = _approval_event
                                yield {"type": "pending_operation", "message": new_op["confirmation_message"], "operation": new_op}
                                try:
                                    await asyncio.wait_for(_approval_event.wait(), timeout=300)
                                except asyncio.TimeoutError:
                                    _pending_approval_events.pop(op_id, None)
                                    observation = f"Operation '{tool_name}' timed out waiting for approval. Skipping."
                                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                                    break
                                _pending_approval_events.pop(op_id, None)
                                resolved_op = pending_operations_store.get(op_id, {})
                                if resolved_op.get("status") == "rejected":
                                    _rej = resolved_op.get("result") or {}
                                    _rej_err = _rej.get("error", "") if isinstance(_rej, dict) else ""
                                    if isinstance(_rej, dict) and _rej.get("source") == "system" and _rej_err:
                                        observation = f"Operation '{tool_name}' was blocked by the system: {_rej_err}. Tell the user exactly why it was blocked and what they need to do."
                                    else:
                                        observation = f"User rejected the '{tool_name}' operation. Do not retry it. Summarise what you know so far and ask what the user wants to do instead."
                                elif resolved_op.get("result") is not None:
                                    exec_result = resolved_op["result"]
                                    observation = sanitize_for_llm(str(exec_result))
                                    yield {"type": "step", "message": f"{tool_name} approved and executed."}
                                else:
                                    observation = f"Operation '{tool_name}' was approved but produced no result."
                            else:
                                observation = sanitize_for_llm(str(exec_res.get("data") or exec_res.get("error") or "No result."))
                        elif tool_name in _obs_registry:
                            import inspect as _inspect
                            tool_info = _obs_registry[tool_name]
                            fn = tool_info["function"]
                            valid_inputs = {k: v for k, v in tool_inputs.items() if k in tool_info.get("inputs", [])}
                            # Coerce numeric params declared as string by the schema
                            for _k, _v in list(valid_inputs.items()):
                                try:
                                    valid_inputs[_k] = int(_v)
                                except (TypeError, ValueError):
                                    pass
                            import logging as _logging
                            _obs_log = _logging.getLogger("ai_service.obs")
                            _obs_log.debug("[OBS] calling tool=%s inputs=%s", tool_name, valid_inputs)
                            try:
                                if _inspect.iscoroutinefunction(fn):
                                    exec_res = await fn(**valid_inputs)
                                else:
                                    exec_res = fn(**valid_inputs)
                                _data = exec_res.get("data")
                                _err = exec_res.get("error")
                                if _err:
                                    observation = f"ELASTICSEARCH TOOL RESULT: error — {_err}"
                                elif _data is not None:
                                    if isinstance(_data, list) and len(_data) == 0:
                                        total = exec_res.get("total", 0)
                                        if "list_indices" in tool_name or "list_data" in tool_name:
                                            observation = (
                                                f"ELASTICSEARCH TOOL RESULT: index/stream listing returned 0 visible results "
                                                f"(total raw={total}, API key may lack monitor privilege). "
                                                "IMPORTANT: indices may still exist and be searchable — "
                                                "proceed to call elasticsearch_search or elasticsearch_get_documents directly."
                                            )
                                        else:
                                            # search / get_documents returned 0 hits
                                            idx = valid_inputs.get("index", "the index")
                                            observation = (
                                                f"ELASTICSEARCH TOOL RESULT: search on '{idx}' returned 0 matching documents. "
                                                f"The query executed successfully (no errors) but found no results. "
                                                f"Suggestions: 1) broaden or remove the time range filter, "
                                                f"2) call elasticsearch_get_mapping on '{idx}' to verify field names, "
                                                f"3) try a broader index pattern like '*' or 'filebeat-*'."
                                            )
                                    elif isinstance(_data, list):
                                        total = exec_res.get("total", len(_data))
                                        lines = [
                                            f"ELASTICSEARCH TOOL RESULT (verbatim — do NOT add or invent indices): "
                                            f"{len(_data)} of {total} indices:"
                                        ]
                                        for i, item in enumerate(_data[:20], 1):
                                            if isinstance(item, dict):
                                                lines.append(f"  {i}. " + " | ".join(f"{k}: {v}" for k, v in list(item.items())[:6]))
                                            else:
                                                lines.append(f"  {i}. {item}")
                                        observation = sanitize_for_llm("\n".join(lines), token_cap=3000)
                                    else:
                                        observation = f"ELASTICSEARCH TOOL RESULT: {sanitize_for_llm(str(_data), token_cap=3000)}"
                                else:
                                    observation = "ELASTICSEARCH TOOL RESULT: no data returned."
                            except Exception as _obs_err:
                                observation = f"Observability tool error: {_obs_err}"
                            _obs_log.debug("[OBS] observation sent to AI (first 500 chars): %s", observation[:500])
                        elif tool_name == "discover_tools":
                            _disc = _registry.discover_tools(tool_inputs.get("intent", ""))
                            _names = [t["name"] for t in _disc["data"]["tools"]]
                            _existing = {t["function"]["name"] for t in tools_schema}
                            _new = [s for s in _registry.schema_for_tools(_names)
                                    if s["function"]["name"] not in _existing]
                            tools_schema.extend(_new)
                            observation = (
                                "Discovered tools now available: "
                                + ", ".join(_names) if _names else "No matching tools found."
                            )
                            yield {"type": "step", "message": f"discover_tools done ({len(_new)} added)."}
                            observation = await _ctx_mgr.trim_tool_result(
                                tool_name, observation, provider, caching_client
                            )
                            messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                            continue
                        elif tool_name in _registry.TOOL_REGISTRY:
                            exec_res = await _registry.execute_tool_async(tool_name, tool_inputs)
                            if isinstance(exec_res, dict) and exec_res.get("requires_confirmation"):
                                pending_op_data = exec_res.get("pending_operation", {})
                                op_id = str(uuid.uuid4())
                                new_op = {
                                    "id": op_id,
                                    "session_id": "global_session",
                                    "tool_name": tool_name,
                                    "tool_inputs": tool_inputs,
                                    "confirmation_message": pending_op_data.get("confirmation_message") or exec_res.get("confirmation_message"),
                                    "risk_level": pending_op_data.get("risk_level") or exec_res.get("risk_level", "medium"),
                                    "created_at": time.time(),
                                    "status": "pending",
                                    "executed_at": None,
                                    "result": None,
                                }
                                from app.api.v1.operations import pending_operations_store
                                pending_operations_store[op_id] = new_op
                                # Register wait event BEFORE yielding so the approval API can set it
                                _approval_event = asyncio.Event()
                                _pending_approval_events[op_id] = _approval_event
                                yield {"type": "pending_operation", "message": new_op["confirmation_message"], "operation": new_op}
                                # Pause loop until user approves or rejects (5-minute timeout)
                                try:
                                    await asyncio.wait_for(_approval_event.wait(), timeout=300)
                                except asyncio.TimeoutError:
                                    _pending_approval_events.pop(op_id, None)
                                    observation = f"Operation '{tool_name}' timed out waiting for approval. Skipping."
                                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                                    break
                                _pending_approval_events.pop(op_id, None)
                                # Check what happened: approved → result stored; rejected → status = rejected
                                resolved_op = pending_operations_store.get(op_id, {})
                                if resolved_op.get("status") == "rejected":
                                    _rej = resolved_op.get("result") or {}
                                    _rej_err = _rej.get("error", "") if isinstance(_rej, dict) else ""
                                    if isinstance(_rej, dict) and _rej.get("source") == "system" and _rej_err:
                                        observation = f"Operation '{tool_name}' was blocked by the system: {_rej_err}. Tell the user exactly why it was blocked and what they need to do."
                                    else:
                                        observation = f"User rejected the '{tool_name}' operation. Do not retry it. Summarise what you know so far and ask what the user wants to do instead."
                                elif resolved_op.get("result") is not None:
                                    exec_result = resolved_op["result"]
                                    observation = sanitize_for_llm(str(exec_result))
                                    yield {"type": "step", "message": f"{tool_name} approved and executed."}
                                else:
                                    observation = f"Operation '{tool_name}' was approved but produced no result."
                            else:
                                observation = sanitize_for_llm(str(exec_res))
                        elif workflow_tool_executors and tool_name in workflow_tool_executors:
                            exec_result = await workflow_tool_executors[tool_name](tool_inputs)
                            observation = sanitize_for_llm(str(exec_result))
                        else:
                            custom_tool = next((t for t in custom_tools if t["name"] == tool_name), None)
                            if custom_tool:
                                observation = sanitize_for_llm(await self._execute_custom_tool(
                                    custom_tool, tool_inputs,
                                    cluster_id=cluster_id,
                                    cluster_context=context,
                                    god_mode_active=god_mode_active,
                                ))
                            else:
                                valid_names = ", ".join(_registry.TOOL_REGISTRY.keys())
                                observation = (
                                    f"ERROR: Tool '{tool_name}' does not exist. "
                                    f"Pick from: {valid_names}"
                                )

                        yield {"type": "step", "message": f"{tool_name} done."}
                        observation = await _ctx_mgr.trim_tool_result(
                            tool_name, observation, provider, caching_client
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": observation,
                        })
                else:
                    # No tool calls — model is done
                    text = text if text and text.strip() else "(No response from model)"
                    if investigation_mode and text != "(No response from model)":
                        observations = [
                            m["content"] for m in messages
                            if m.get("role") == "tool" and m.get("content")
                        ]
                        if observations:
                            yield {"type": "step", "message": "Reviewing findings..."}
                            review = await self._run_final_review(
                                query, observations, text, caching_client
                            )
                            yield {
                                "type": "result",
                                "message": review.get("answer", text),
                                "structured": {
                                    "root_cause": review.get("root_cause"),
                                    "evidence": review.get("evidence"),
                                    "recommended_fix": review.get("recommended_fix"),
                                },
                            }
                            return
                    yield {"type": "result", "message": text}
                    return

            yield {"type": "result", "message": "Agent reached max iterations without a final answer."}
        except Exception as e:
            yield {"type": "result", "message": f"Agent error: {str(e)}"}

ai_service = AIService()
