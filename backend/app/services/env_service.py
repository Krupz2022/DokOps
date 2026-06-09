import os
import json
import base64
from typing import Dict, List, Optional
from app.core.encryption import encrypt, decrypt

# Keys that must never be overridden by user-supplied env vars.
# Overriding these can redirect binary lookups, inject shared libraries,
# hijack Kubernetes configs, or alter shell interpreter behaviour.
PROTECTED_ENV_KEYS: frozenset[str] = frozenset({
    "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "HOME", "USER", "LOGNAME", "SHELL", "ENV", "BASH_ENV", "CDPATH",
    "IFS", "KUBECONFIG", "AWS_SHARED_CREDENTIALS_FILE",
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EXEC_PATH",
    "SUDO_COMMAND", "SUDO_USER",
})


class EnvVarService:
    """
    Manages environment variables that get injected into toolset command execution.
    Stored in a JSON file alongside the toolsets directory.
    Values are base64-encoded for basic obfuscation (not true encryption).
    """

    def __init__(self, storage_path: str):
        self.storage_path = storage_path

    def _load(self) -> Dict[str, str]:
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
            result = {}
            for k, v in data.items():
                try:
                    result[k] = decrypt(v)  # Fernet-encrypted
                except Exception:
                    try:
                        result[k] = base64.b64decode(v).decode("utf-8")  # legacy base64 migration
                    except Exception:
                        result[k] = v
            return result
        except Exception as e:
            print(f"Error loading env vars: {e}")
            return {}

    def _save(self, env_vars: Dict[str, str]) -> None:
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        # Encrypt with Fernet (replaces legacy base64)
        encrypted = {k: encrypt(v) for k, v in env_vars.items()}
        with open(self.storage_path, "w") as f:
            json.dump(encrypted, f, indent=2)

    def list_vars(self) -> List[Dict[str, str]]:
        """List all env vars with masked values."""
        env_vars = self._load()
        result = []
        for key, value in env_vars.items():
            masked = value[:2] + "*" * max(0, len(value) - 4) + value[-2:] if len(value) > 4 else "****"
            result.append({"key": key, "value_masked": masked})
        return result

    def set_var(self, key: str, value: str) -> bool:
        """Set or update an environment variable."""
        try:
            key = key.strip().upper()
            if not key:
                return False
            if key in PROTECTED_ENV_KEYS:
                return False
            env_vars = self._load()
            env_vars[key] = value
            self._save(env_vars)
            return True
        except Exception as e:
            print(f"Error setting env var: {e}")
            return False

    def delete_var(self, key: str) -> bool:
        """Delete an environment variable."""
        try:
            env_vars = self._load()
            if key in env_vars:
                del env_vars[key]
                self._save(env_vars)
                return True
            return False
        except Exception as e:
            print(f"Error deleting env var: {e}")
            return False

    def get_all_as_dict(self) -> Dict[str, str]:
        """Get all env vars as a plain dict for injection into subprocess."""
        return self._load()


# Instantiate a global service instance
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_app_dir = os.path.dirname(current_dir)
env_vars_path = os.path.join(backend_app_dir, "toolsets", ".env_vars.json")

env_var_service = EnvVarService(env_vars_path)
