import sys
import os

# Ensure the backend directory is on the path so `app` can be imported
sys.path.insert(0, os.path.dirname(__file__))

import pytest


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Clear process-wide caches before each test so DB swaps take effect."""
    try:
        from app.core import settings_cache
        settings_cache.invalidate()
    except Exception:
        pass
    yield
