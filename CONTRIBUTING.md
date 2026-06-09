# Contributing to DokOps

Thank you for your interest in contributing! DokOps is a community-driven project and we welcome contributions of all kinds — bug fixes, new features, documentation improvements, and test coverage.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Submitting a Pull Request](#submitting-a-pull-request)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Commit Messages](#commit-messages)
- [Branch Strategy](#branch-strategy)
- [Testing](#testing)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Please report unacceptable behaviour to the maintainers via GitHub Issues.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/DokOps.git
   cd DokOps
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/Krupz2022/DokOps.git
   ```
4. Create a branch for your work (see [Branch Strategy](#branch-strategy)).

---

## How to Contribute

### Reporting Bugs

Before opening a bug report, please search existing issues to avoid duplicates.

When filing a bug, include:
- DokOps version / commit SHA
- Steps to reproduce (minimal and specific)
- Expected vs. actual behaviour
- Relevant logs or screenshots
- Environment: OS, Python version, browser, Kubernetes version (if applicable)

Use the **Bug Report** issue template.

### Suggesting Features

Open a **Feature Request** issue. Describe:
- The problem you're solving
- Your proposed solution
- Any alternatives you considered

For large changes, discuss the idea in an issue **before** writing code — this avoids wasted effort if the direction isn't a fit.

### Submitting a Pull Request

1. Keep PRs **focused** — one feature or fix per PR. Split unrelated changes.
2. Base your branch off `develop`, not `main`.
3. Fill in the **Pull Request template** completely.
4. All CI checks must pass before review.
5. At least one maintainer approval is required to merge.
6. Squash-merge is preferred for feature branches; rebase-merge for hotfixes.

---

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 20+
- Docker (optional, for full-stack testing)
- A kubeconfig file — or use Mock Mode (no cluster needed)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run with mock Kubernetes (no cluster required)
K8S_MOCK_MODE=true uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:5173
```

### Full Stack (Docker Compose)

```bash
cd deployment
cp .env.example .env   # fill in AUTH_SECRET_KEY and an AI provider key
docker compose up -d
```

---

## Coding Standards

### Python (Backend)

- **Type hints** are mandatory on all function signatures.
- Use `async/await` for all I/O-bound operations (database, Kubernetes, HTTP).
- Catch specific exceptions — never bare `except:`.
- Return HTTP `4xx`/`5xx` with a JSON `detail` field on errors.
- No hardcoded secrets or connection strings — use `pydantic-settings` and environment variables.
- Follow existing patterns in `backend/app/services/` for new services.

### TypeScript (Frontend)

- Functional components only. No class components.
- No `any` — define an interface for every API response shape.
- Use `clsx` + `tailwind-merge` for conditional classes.
- All API calls go through `frontend/src/lib/api.ts`.
- Modals use React Portals (see existing modal components for reference).

### General

- **No commented-out code** in PRs.
- **No debug `print()` / `console.log()`** in production paths.
- Write code that is obviously correct rather than clever.
- Security first — never log credentials, tokens, or secret values. See `backend/app/services/sanitizer.py`.

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short summary in present tense>

<optional body — explain the WHY, not the what>
```

**Types:**

| Type | When to use |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding or fixing tests |
| `refactor` | Code change that is neither a fix nor a feature |
| `chore` | Build process, dependency updates, tooling |
| `perf` | Performance improvement |

**Examples:**

```
feat: add Confluence space sync to RAG knowledge base

fix: resolve race condition in minion WebSocket reconnect loop

docs: add Vault credential token syntax to README
```

- Keep the subject line under 72 characters.
- Use the body to explain motivation and trade-offs, not mechanics.
- Reference issues with `Closes #123` or `Fixes #456` at the end of the body.

---

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready releases |
| `develop` | Integration branch — all PRs target here |
| `feat/<name>` | New feature work |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation changes |
| `chore/<name>` | Tooling, deps, CI |

**Never push directly to `main`.** All changes flow through `develop` via pull request.

---

## Testing

### Backend

```bash
cd backend
K8S_MOCK_MODE=true pytest
```

New code must include tests. Place them in `backend/tests/` following the existing naming convention (`test_<module>.py`).

- Unit tests should use in-memory SQLite (`sqlite://`) — see existing tests for the pattern.
- Mock external services (Kubernetes API, AI providers, observability tools) — do not make real network calls in tests.
- Aim for a test that proves the behaviour from the outside, not one that just exercises internal implementation.

### Frontend

```bash
cd frontend
npm run test       # Vitest unit tests
npm run typecheck  # TypeScript strict check
npm run lint       # ESLint
```

---

## Questions?

Open a [Discussion](https://github.com/Krupz2022/DokOps/discussions) or file an issue with the `question` label. We're happy to help.
