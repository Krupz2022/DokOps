import os
import re as _re
import yaml
from typing import List, Dict, Any, Optional

_TOOLSET_ID_RE = _re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_toolset_id(toolset_id: str) -> str:
    if ".." in toolset_id or "/" in toolset_id or "\\" in toolset_id:
        raise ValueError(f"Invalid toolset ID (path traversal detected): {toolset_id!r}")
    safe = os.path.basename(toolset_id)
    if not safe or not _TOOLSET_ID_RE.match(safe):
        raise ValueError(f"Invalid toolset ID: {toolset_id!r}")
    return safe


def _load_yaml_files(directory: str) -> List[Dict[str, Any]]:
    result = []
    if not os.path.exists(directory):
        return result
    for filename in os.listdir(directory):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            try:
                with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data:
                        data["id"] = filename.replace(".yaml", "").replace(".yml", "")
                        result.append(data)
            except Exception as e:
                print(f"Error loading toolset {filename}: {e}")
    return result


class ToolsetService:
    def __init__(self, toolsets_dir: str, builtin_dir: Optional[str] = None):
        self.toolsets_dir = toolsets_dir
        self.builtin_dir = builtin_dir or os.path.join(toolsets_dir, "builtin")

    def list_toolsets(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.toolsets_dir):
            os.makedirs(self.toolsets_dir, exist_ok=True)
        return _load_yaml_files(self.toolsets_dir)

    def list_builtin_toolsets(self) -> List[Dict[str, Any]]:
        toolsets = _load_yaml_files(self.builtin_dir)
        for ts in toolsets:
            ts["builtin"] = True
        return toolsets

    def get_toolset(self, toolset_id: str) -> Optional[Dict[str, Any]]:
        toolset_id = _validate_toolset_id(toolset_id)
        for ext in [".yaml", ".yml"]:
            path = os.path.join(self.toolsets_dir, f"{toolset_id}{ext}")
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        data = yaml.safe_load(f)
                        if data:
                            data["id"] = toolset_id
                            return data
                except Exception as e:
                    print(f"Error reading toolset {toolset_id}: {e}")
        return None

    def get_toolset_raw(self, toolset_id: str) -> Optional[str]:
        toolset_id = _validate_toolset_id(toolset_id)
        for ext in [".yaml", ".yml"]:
            path = os.path.join(self.toolsets_dir, f"{toolset_id}{ext}")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    print(f"Error reading raw toolset {toolset_id}: {e}")
        return None

    def save_toolset(self, toolset_id: str, content: str) -> bool:
        try:
            toolset_id = _validate_toolset_id(toolset_id)
            data = yaml.safe_load(content)
            if not isinstance(data, dict) or not data:
                return False
            os.makedirs(self.toolsets_dir, exist_ok=True)
            filename = f"{toolset_id}.yaml" if not toolset_id.endswith(".yaml") else toolset_id
            path = os.path.join(self.toolsets_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"Error saving toolset: {e}")
            return False


current_dir = os.path.dirname(os.path.abspath(__file__))
backend_app_dir = os.path.dirname(current_dir)
toolsets_path = os.path.join(backend_app_dir, "toolsets")
builtin_path = os.path.join(toolsets_path, "builtin")

toolset_service = ToolsetService(toolsets_dir=toolsets_path, builtin_dir=builtin_path)
