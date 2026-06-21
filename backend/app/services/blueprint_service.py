from __future__ import annotations

import yaml


def merge_blueprints(ordered_yaml_bodies: list[str]) -> list[dict]:
    """Concatenate each body's `resources` list in order; later same-id states replace earlier."""
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for body in ordered_yaml_bodies:
        if not body or not body.strip():
            continue
        doc = yaml.safe_load(body) or {}
        # Support both 'resources' and 'states' keys
        states_list = doc.get("resources", []) or doc.get("states", []) or []
        for state in states_list:
            sid = state.get("id")
            if not sid:
                raise ValueError("every state needs an `id`")
            if sid not in by_id:
                order.append(sid)
            by_id[sid] = state
    return [by_id[sid] for sid in order]


def collect_referenced_sources(
    states: list[dict], sources_by_name: dict[str, str]
) -> dict[str, str]:
    """Return only the sources referenced by a file-state's `source`."""
    wanted = {s.get("source") for s in states if s.get("type") == "file" and s.get("source")}
    return {name: content for name, content in sources_by_name.items() if name in wanted}
