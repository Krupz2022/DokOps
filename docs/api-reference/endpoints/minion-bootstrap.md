# Minion Bootstrap (Other)

These routes are **not part of the `/api/v1` API** and are **hidden from Swagger** (`/docs`). They exist to help a brand-new minion install itself: download the agent code and install scripts, fetch blueprint source files, and install Python packages through DokOps (a PyPI proxy) when the server itself has no direct internet access on the target machine.

They live directly on the app root (no `/api/v1` prefix). Base URL: `http://localhost:8000`.

> **Who calls these?** The minion installer (`install.sh` / `install.ps1`) and the running agent — not you, normally. They're documented here for completeness and troubleshooting.

---

## File downloads (no auth)

These serve files bundled in the server's `minion/` directory. If a file isn't bundled, you get `404 "<file> not bundled"`.

| Method & Path | What it returns | Content type |
|---------------|-----------------|--------------|
| `GET /minion/agent.py` | The minion agent program. | `text/x-python` |
| `GET /minion/blueprint.py` | The blueprint execution engine. | `text/x-python` |
| `GET /minion/install.sh` | Linux/macOS install script. | `text/x-sh` |
| `GET /minion/uninstall.sh` | Linux/macOS uninstall script. | `text/x-sh` |
| `GET /minion/install.ps1` | Windows (PowerShell) install script. | `text/plain` |
| `GET /minion/uninstall.ps1` | Windows (PowerShell) uninstall script. | `text/plain` |

**Auth required?** No.

**curl example:**

```bash
curl -O http://localhost:8000/minion/install.sh
```

**Common errors:** `404` if that file isn't bundled in this build.

---

## GET /minion/source/{source_id}

**What this does:** Returns the raw bytes of a blueprint **source** file (a script/config attached to a blueprint), so the agent can fetch what it needs during a blueprint run.

**Auth required?** Yes — but via an **enrollment token** query parameter, not a login. The token must match the server's auto-accept enrollment key.

**Path parameters:** `source_id` (string, required).

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `token` | string | yes | A valid enrollment token. |

**curl example:**

```bash
curl "http://localhost:8000/minion/source/src_123?token=ENROLLMENT_TOKEN" -o setup.sh
```

**Response:** the file's raw bytes (`application/octet-stream`). Base64-encoded sources are decoded for you.

**Common errors:**

| Code | Meaning |
|------|---------|
| `401` | Missing or invalid enrollment token. |
| `404` | No source with that ID. |

---

## GET /minion/simple/{package_name}/

**What this does:** A **PyPI "simple index" proxy** — it fetches the package index from `pypi.org` and rewrites the download links to go back through this server. This lets a minion install Python packages even when it can only reach DokOps (not the public internet). It's the equivalent of pointing `pip` at DokOps as a package index.

**Auth required?** No.

**Path parameters:** `package_name` (string, required) — the PyPI package name.

**curl example (how a minion uses it):**

```bash
pip install --index-url http://localhost:8000/minion/simple/ requests
```

**Response:** an HTML index page (PyPI's "simple" format) with links rewritten to `/minion/pypi-file/?url=...`.

**Common errors:** the upstream PyPI status is passed through (e.g. `404` for an unknown package).

---

## GET /minion/pypi-file/

**What this does:** Streams a single package file (a wheel or tarball) from PyPI through this server — the destination of the rewritten links from the index proxy above.

**Auth required?** No.

**Query parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | string | yes | The upstream file URL to stream. Must be on `pypi.org` or `files.pythonhosted.org`. |

**curl example:**

```bash
curl "http://localhost:8000/minion/pypi-file/?url=https%3A%2F%2Ffiles.pythonhosted.org%2F...%2Frequests-2.31.0-py3-none-any.whl" -O
```

**Response:** the file streamed as `application/octet-stream` with a `Content-Disposition` filename.

**Common errors:**

| Code | Meaning |
|------|---------|
| `400` | "URL not allowed" — the URL's host isn't `pypi.org` or `files.pythonhosted.org` (a safety allow-list). |

---

## Also at the app root

These two are visible (not hidden) but live outside `/api/v1`:

| Method & Path | What it does | Auth | Example response |
|---------------|--------------|------|------------------|
| `GET /` | Liveness root. | None | `{"message": "MCP Kubernetes Server is Running"}` |
| `GET /health` | Health check. | None | `{"status": "ok"}` |

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```
