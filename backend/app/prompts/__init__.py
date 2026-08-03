"""Loads the DokOps agent policy from dokops.md.

The policy is baked into the image and read once at import. There is
deliberately no reload endpoint, no API route and no SystemSetting backing
this: the policy is global and not user-editable.
"""
import pathlib
import re
from typing import Dict

_POLICY_FILE = pathlib.Path(__file__).parent / "dokops.md"
_ANCHOR_RE = re.compile(r"^<!--\s*id:\s*([a-z_]+)\s*-->\s*$", re.MULTILINE)


def _load(path: pathlib.Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    parts = _ANCHOR_RE.split(text)
    # split() yields [preamble, id1, body1, id2, body2, ...]
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


POLICY: Dict[str, str] = _load(_POLICY_FILE)
