import os
import tempfile
import pytest
from app.services.runbook_service import RunbookService


@pytest.fixture
def tmp_runbook_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def service(tmp_runbook_dir):
    return RunbookService(tmp_runbook_dir)


def write_md(directory, filename, content):
    with open(os.path.join(directory, filename), "w") as f:
        f.write(content)


def test_list_runbooks_empty(service):
    assert service.list_runbooks() == []


def test_list_runbooks_returns_metadata(service, tmp_runbook_dir):
    write_md(tmp_runbook_dir, "jwt_triage.md", "---\nname: JWT Triage\ntrigger: jwt error\n---\n\n## Steps\n1. Check logs")
    runbooks = service.list_runbooks()
    assert len(runbooks) == 1
    assert runbooks[0]["id"] == "jwt_triage"
    assert runbooks[0]["name"] == "JWT Triage"
    assert runbooks[0]["trigger"] == "jwt error"
    assert "## Steps" in runbooks[0]["body"]


def test_list_runbooks_ignores_non_md(service, tmp_runbook_dir):
    write_md(tmp_runbook_dir, "old.yaml", "name: old")
    write_md(tmp_runbook_dir, "valid.md", "---\nname: Valid\ntrigger: test\n---\n\nbody")
    runbooks = service.list_runbooks()
    assert len(runbooks) == 1
    assert runbooks[0]["id"] == "valid"


def test_get_runbook_returns_none_if_missing(service):
    assert service.get_runbook("nonexistent") is None


def test_get_runbook_returns_data(service, tmp_runbook_dir):
    write_md(tmp_runbook_dir, "jwt_triage.md", "---\nname: JWT Triage\ntrigger: jwt error\n---\n\n## Steps\n1. Check logs")
    rb = service.get_runbook("jwt_triage")
    assert rb["name"] == "JWT Triage"
    assert rb["trigger"] == "jwt error"
    assert "## Steps" in rb["body"]


def test_save_runbook_writes_md_file(service, tmp_runbook_dir):
    content = "---\nname: Test\ntrigger: test trigger\n---\n\n## Steps\n1. Do thing"
    result = service.save_runbook("test_rb", content)
    assert result is True
    assert os.path.exists(os.path.join(tmp_runbook_dir, "test_rb.md"))


def test_save_runbook_rejects_missing_name(service):
    content = "---\ntrigger: test trigger\n---\n\n## Steps\n1. Do thing"
    assert service.save_runbook("bad_rb", content) is False


def test_save_runbook_rejects_missing_trigger(service):
    content = "---\nname: Test\n---\n\n## Steps\n1. Do thing"
    assert service.save_runbook("bad_rb", content) is False


def test_save_runbook_rejects_invalid_frontmatter(service):
    content = "no frontmatter at all just markdown"
    assert service.save_runbook("bad_rb", content) is False
