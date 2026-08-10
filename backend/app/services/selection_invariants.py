"""Startup assertions for the tool-selection cascade.

Four instances of ONE omission class: a fact declared in one place and relied
on in another, with nothing to fail when they diverge. Lives in its own module
because it spans presweep, the registry and ai_service, and presweep must not
import ai_service (ai_service imports presweep).
"""
import inspect
import re


def verify_selection_invariants() -> None:
    from app.services import presweep
    from app.tools.registry import TOOL_REGISTRY

    problems: list[str] = []

    # 1 — RHS validity: every tool the table names must exist.
    for reason, tools in presweep.SYMPTOM_TOOLS.items():
        for tool in tools:
            if tool not in TOOL_REGISTRY:
                problems.append(f"SYMPTOM_TOOLS[{reason!r}] names unknown tool {tool!r}")

    # 2 — the reachability lockstep, both directions.
    surface = presweep.evidence_reasons()
    for reason in presweep.SYMPTOM_TOOLS:
        if reason not in surface:
            problems.append(
                f"SYMPTOM_TOOLS[{reason!r}] is dead on arrival: presweep cannot emit that "
                f"reason. Widen the evidence surface first, or drop the row."
            )
    for reason in surface:
        if reason not in presweep.SYMPTOM_TOOLS and reason not in presweep.INTENTIONALLY_UNMAPPED:
            problems.append(
                f"evidence reason {reason!r} has no SYMPTOM_TOOLS row and is not in "
                f"INTENTIONALLY_UNMAPPED — tier 1 would silently emit nothing for it"
            )

    # 3 — write guard: the dispatcher reacts to the return value, never to this
    #     flag, so a declared-but-unguarded write tool mutates immediately.
    for name, info in TOOL_REGISTRY.items():
        if info.get("operation_type") != "write":
            continue
        fn = info.get("function")
        try:
            src = inspect.getsource(fn)
            params = inspect.signature(fn).parameters
        except (OSError, TypeError, ValueError):
            problems.append(f"write tool {name!r}: source unavailable, cannot verify guard")
            continue
        if "confirmed" not in params:
            problems.append(f"write tool {name!r} has no 'confirmed' parameter")
        elif not re.search(r"if\s+not\s+confirmed", src):
            problems.append(f"write tool {name!r} accepts 'confirmed' but never guards on it")

    # 4 — ordering completeness: a domain absent from the tuple lands undefined.
    from app.services.ai_service import AIService
    emittable = set(AIService._SERVICE_TOOL_MAP.values())
    for domain in sorted(emittable - set(AIService._DOMAIN_ORDER)):
        problems.append(
            f"domain {domain!r} is emittable by tier 1b/2 but absent from _DOMAIN_ORDER")

    if problems:
        raise RuntimeError(
            "tool-selection invariants violated:\n  - " + "\n  - ".join(problems))
