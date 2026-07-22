import pytest

from app.services.blueprint_service import merge_blueprints, render_vars

BODY = """
vars:
  path_pref: /opt/dokops
  ver: "1.4"
resources:
  - id: cfg
    type: file
    name: ${path_pref}/app.conf
    source: conf-${ver}.tmpl
"""


def test_substitutes_in_string_values():
    [state] = merge_blueprints([BODY])
    assert state["name"] == "/opt/dokops/app.conf"
    assert state["source"] == "conf-1.4.tmpl"


def test_adjacent_text_is_unambiguous():
    body = """
vars:
  path_pref: /opt/dokops
resources:
  - id: b
    type: file
    name: ${path_pref}bin
"""
    assert merge_blueprints([body])[0]["name"] == "/opt/dokopsbin"


def test_undefined_variable_raises_naming_it():
    body = """
vars:
  path_pref: /opt/dokops
resources:
  - id: cfg
    type: file
    name: ${path_prefix}/app.conf
"""
    with pytest.raises(ValueError) as e:
        merge_blueprints([body])
    assert "path_prefix" in str(e.value) and "cfg" in str(e.value)


def test_vars_are_file_local():
    """A later file must not see an earlier file's vars — that's the whole point."""
    a = """
vars:
  path_pref: /opt/a
resources:
  - id: one
    type: file
    name: ${path_pref}/x
"""
    b = """
vars:
  path_pref: /opt/b
resources:
  - id: two
    type: file
    name: ${path_pref}/y
"""
    merged = merge_blueprints([a, b])
    assert [s["name"] for s in merged] == ["/opt/a/x", "/opt/b/y"]


def test_file_without_vars_block_is_untouched():
    """Back-compat: an existing blueprint with a literal ${...} must keep working.

    Shell snippets in cmd states are full of ${HOME}-style text; opting in via a
    vars: block is what enables substitution.
    """
    body = """
resources:
  - id: sh
    type: cmd
    run: echo ${HOME}/bin
"""
    assert merge_blueprints([body])[0]["run"] == "echo ${HOME}/bin"


def test_non_strings_and_keys_untouched():
    body = """
vars:
  mode_val: "0640"
resources:
  - id: cfg
    type: file
    name: /etc/x
    mode: ${mode_val}
    replace: true
    retries: 3
"""
    [state] = merge_blueprints([body])
    assert state["mode"] == "0640"
    assert state["replace"] is True and state["retries"] == 3


def test_substitutes_in_nested_structures():
    body = """
vars:
  root: /srv
resources:
  - id: n
    type: cmd
    run: ls
    env:
      HOME: ${root}/home
    args:
      - ${root}/a
      - ${root}/b
"""
    [state] = merge_blueprints([body])
    assert state["env"]["HOME"] == "/srv/home"
    assert state["args"] == ["/srv/a", "/srv/b"]


def test_tab_indentation_names_the_blueprint():
    """A raw ScannerError says "line 2" without saying line 2 of what."""
    body = "resources:\n  - id: cfg\n    type: file\n\tmode: 0755\n"
    with pytest.raises(ValueError) as e:
        merge_blueprints([body], ["orgs/acme/web.yaml"])
    msg = str(e.value)
    assert "orgs/acme/web.yaml" in msg
    assert "invalid YAML" in msg
    assert "line 4" in msg          # the yaml error's own position survives


def test_parse_error_without_names_still_reports_position():
    body = "resources:\n\tbad: 1\n"
    with pytest.raises(ValueError) as e:
        merge_blueprints([body])
    assert "blueprint #1" in str(e.value)


def test_render_vars_passthrough_without_variables():
    states = [{"id": "x", "name": "${literal}"}]
    assert render_vars(states, {}) == states
