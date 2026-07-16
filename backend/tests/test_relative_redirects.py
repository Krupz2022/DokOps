# Trailing-slash 307s must carry a RELATIVE Location: behind TLS termination the
# app sees http, and an absolute http:// Location gets blocked as mixed content.
import pytest

from app.models.user import User  # noqa: F401
from app.models.minion import Minion  # noqa: F401
from app.models.blueprint import Blueprint  # noqa: F401
from app.models.patch import Organisation  # noqa: F401
from app.models.activation_key import ActivationKey, KeyBlueprint  # noqa: F401


@pytest.fixture(name="client")
def client_fixture(isolated_client):
    return isolated_client


def test_slash_redirect_location_is_relative(client):
    # /api/v1/minions (route is "/") -> 307 to the slashed path, relative form
    resp = client.get("/api/v1/minions", follow_redirects=False)
    assert resp.status_code in (307, 308)
    loc = resp.headers["location"]
    assert loc.startswith("/"), f"expected relative Location, got {loc}"
    assert loc.endswith("/api/v1/minions/")


def test_external_redirects_untouched(client):
    # a redirect to a different host (e.g. SSO IdP) must keep its absolute URL
    from fastapi.responses import RedirectResponse
    app = client.app

    @app.get("/test-external-redirect")
    async def _ext():
        return RedirectResponse(url="https://idp.example.com/authorize?x=1", status_code=302)

    resp = client.get("/test-external-redirect", follow_redirects=False)
    assert resp.headers["location"] == "https://idp.example.com/authorize?x=1"
