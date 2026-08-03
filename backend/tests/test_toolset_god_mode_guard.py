"""Guard test: every destructive custom-toolset command must be god_mode-gated.

Context: ai_service._execute_custom_tool() only blocks a custom tool when
`tool_def.get("god_mode")` is truthy (see ai_service.py:754). There is no
toolset-level default and no schema validation on the YAML files under
app/toolsets/ - a missing `god_mode` key silently means "runs unguarded",
even if the tool's own description claims it requires God Mode.

This test loads every YAML toolset file on disk and asserts that any tool
whose command line invokes a verb capable of mutating or destroying cluster
state carries `god_mode: true`. Detection is based on the actual command
string, not the tool's name, so a tool called e.g. `helm_apply_config` that
happens to shell out to `helm delete` is still caught.

Genuine read-only tools whose command text merely contains a destructive
word (a diff/dry-run subcommand, etc.) are excused via EXEMPTIONS below -
never by weakening the verb list or the regex.
"""
import os
import re
from typing import Dict, List, Tuple

import pytest
import yaml

TOOLSETS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "app", "toolsets"
)

# Verbs that can mutate or destroy cluster/release state if actually executed.
# Matched as whole words against the tool's `command` (or `script`) string so
# that e.g. "upgrade" doesn't also match "downgrade", and "rm" doesn't match
# "confirm". Extend this list as new destructive verbs show up in toolsets.
DESTRUCTIVE_VERBS = [
    "delete",
    "uninstall",
    "rollback",
    "upgrade",
    "install",
    "apply",
    "scale",
    "drain",
    "evict",
    "patch",
    "replace",
    "destroy",
    "rm",
    "--force",
]

# Matches "--force" literally, or any other verb as a standalone word.
_VERB_PATTERNS = {
    verb: re.compile(r"--force" if verb == "--force" else rf"\b{re.escape(verb)}\b")
    for verb in DESTRUCTIVE_VERBS
}

# (toolset_file, tool_name) -> one-line justification for why this tool is
# excused despite its command matching a destructive verb. Only genuinely
# read-only / dry-run tools belong here. Every entry must be reasoned about,
# not rubber-stamped.
EXEMPTIONS: Dict[Tuple[str, str], str] = {
    ("helm_toolset.yaml", "helm_diff_upgrade"): (
        "`helm diff upgrade` (helm-diff plugin) only computes and prints a "
        "diff against the live release; it never calls Tiller/the cluster "
        "API to apply changes. It is the recommended dry-run preview to run "
        "before helm_upgrade_*, so gating it behind God Mode would block a "
        "safe diagnostic rather than a mutation."
    ),
}


def _iter_toolset_files() -> List[str]:
    paths = []
    for root, _dirs, files in os.walk(TOOLSETS_DIR):
        for fname in files:
            if fname.endswith(".yaml") or fname.endswith(".yml"):
                paths.append(os.path.join(root, fname))
    return sorted(paths)


def _iter_tools() -> List[Tuple[str, str, Dict]]:
    """Yields (filename, toolset_name, tool_def) for every tool in every file."""
    out = []
    for path in _iter_toolset_files():
        fname = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            continue
        for ts_name, ts_data in data.items():
            if not (isinstance(ts_data, dict) and "tools" in ts_data):
                continue
            for tool in ts_data["tools"]:
                out.append((fname, ts_name, tool))
    return out


def _matched_verbs(cmd: str) -> List[str]:
    return [verb for verb, pattern in _VERB_PATTERNS.items() if pattern.search(cmd)]


def test_toolset_files_exist():
    """Sanity check: fail loudly (not silently pass-on-nothing) if the dir moved."""
    assert _iter_toolset_files(), (
        f"No YAML toolset files found under {TOOLSETS_DIR!r} - "
        "did the toolsets directory move?"
    )


def test_every_destructive_toolset_command_requires_god_mode():
    violations = []
    for fname, ts_name, tool in _iter_tools():
        tool_name = tool.get("name", "<unnamed>")
        cmd = tool.get("command") or tool.get("script") or ""
        verbs = _matched_verbs(cmd)
        if not verbs:
            continue
        if (fname, tool_name) in EXEMPTIONS:
            continue
        if tool.get("god_mode") is True:
            continue
        violations.append(
            f"{fname}::{ts_name}::{tool_name} runs {verbs} via command "
            f"{cmd!r} but is missing `god_mode: true`. Either add the flag "
            f"or add an explicit, justified EXEMPTIONS entry in "
            f"tests/test_toolset_god_mode_guard.py."
        )

    assert not violations, "Ungated destructive toolset commands found:\n" + "\n".join(
        violations
    )


def test_exemptions_reference_real_tools():
    """An exemption for a tool that no longer exists (renamed/removed) is dead
    weight that silently widens the next real gap - keep the allowlist honest."""
    known = {(fname, tool.get("name")) for fname, _ts, tool in _iter_tools()}
    stale = [key for key in EXEMPTIONS if key not in known]
    assert not stale, f"Stale EXEMPTIONS entries (tool no longer exists): {stale}"


def test_exempted_tools_still_match_a_destructive_verb():
    """If an exempted tool's command was edited to no longer match any verb,
    the exemption is meaningless clutter - remove it so the list stays honest."""
    by_key = {(fname, tool.get("name")): tool for fname, _ts, tool in _iter_tools()}
    for key in EXEMPTIONS:
        tool = by_key.get(key)
        if tool is None:
            continue  # covered by test_exemptions_reference_real_tools
        cmd = tool.get("command") or tool.get("script") or ""
        assert _matched_verbs(cmd), (
            f"{key} is exempted but its command no longer matches any "
            "destructive verb - the exemption is stale, remove it."
        )
