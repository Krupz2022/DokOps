from app.services.blueprint_service import merge_blueprints, collect_referenced_sources


def test_merge_last_wins_by_id():
    org = """
resources:
  - id: nginx-pkg
    type: pkg
    name: nginx
    ensure: present
  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf
"""
    group = """
resources:
  - id: nginx-conf
    type: file
    path: /etc/nginx/nginx.conf
    source: nginx.conf
    mode: "0640"
"""
    merged = merge_blueprints([org, group])  # org first, group overrides
    ids = [s["id"] for s in merged]
    assert ids == ["nginx-pkg", "nginx-conf"]
    conf = next(s for s in merged if s["id"] == "nginx-conf")
    assert conf["mode"] == "0640"  # group's version won


def test_collect_only_referenced_sources():
    states = [{"id": "c", "type": "file", "source": "nginx.conf"}]
    pool = {"nginx.conf": "data", "unused.conf": "x"}
    got = collect_referenced_sources(states, pool)
    assert got == {"nginx.conf": "data"}


def test_merge_ignores_empty_body():
    merged = merge_blueprints(["", "resources:\n  - id: a\n    type: cmd\n    name: 'echo hi'"])
    assert [s["id"] for s in merged] == ["a"]
