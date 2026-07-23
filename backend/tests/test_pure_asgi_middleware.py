# Guards the BaseHTTPMiddleware → pure-ASGI conversion: BaseHTTPMiddleware
# cancel-scopes SSE streams on client disconnect and leaks pooled asyncpg
# connections (pool exhaustion → AI chat stops responding).


def test_no_basehttp_middleware_in_stack():
    """No middleware may subclass BaseHTTPMiddleware (incl. @app.middleware sugar)."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from app.main import app

    offenders = [m.cls.__name__ for m in app.user_middleware if issubclass(m.cls, BaseHTTPMiddleware)]
    assert offenders == [], f"BaseHTTPMiddleware-based middleware found: {offenders}"


def test_relative_redirect_rewrites_same_host_location():
    """RelativeRedirectMiddleware still rewrites absolute same-host Locations."""
    import anyio
    from app.main import RelativeRedirectMiddleware

    sent = []

    async def inner_app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 307,
            "headers": [(b"location", b"http://myhost/api/v1/things/?a=1")],
        })
        await send({"type": "http.response.body", "body": b""})

    async def run():
        mw = RelativeRedirectMiddleware(inner_app)
        scope = {"type": "http", "headers": [(b"host", b"myhost")]}

        async def send(message):
            sent.append(message)

        await mw(scope, None, send)

    anyio.run(run)
    headers = dict(sent[0]["headers"])
    assert headers[b"location"] == b"/api/v1/things/?a=1"


def test_relative_redirect_leaves_external_host_untouched():
    import anyio
    from app.main import RelativeRedirectMiddleware

    sent = []

    async def inner_app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": [(b"location", b"https://idp.example.com/login")],
        })
        await send({"type": "http.response.body", "body": b""})

    async def run():
        mw = RelativeRedirectMiddleware(inner_app)
        scope = {"type": "http", "headers": [(b"host", b"myhost")]}

        async def send(message):
            sent.append(message)

        await mw(scope, None, send)

    anyio.run(run)
    headers = dict(sent[0]["headers"])
    assert headers[b"location"] == b"https://idp.example.com/login"
