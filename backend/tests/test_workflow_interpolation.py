# backend/tests/test_workflow_interpolation.py
import pytest
from app.services.workflow_service import interpolate_variables, interpolate_config


def test_interpolates_input_var():
    context = {"input": {"jenkins_url": "http://jenkins/job/1"}, "steps": {}}
    result = interpolate_variables("URL is {{input.jenkins_url}}", context)
    assert result == "URL is http://jenkins/job/1"


def test_interpolates_step_var():
    context = {
        "input": {},
        "steps": {"build_log": {"result": "FAILURE", "number": 42}},
    }
    result = interpolate_variables("Build {{steps.build_log.number}} result: {{steps.build_log.result}}", context)
    assert result == "Build 42 result: FAILURE"


def test_interpolates_nested_dict():
    config = {
        "summary": "Build failed: {{input.branch}}",
        "description": "Log: {{steps.build_log.result}}",
    }
    context = {"input": {"branch": "main"}, "steps": {"build_log": {"result": "FAILURE"}}}
    result = interpolate_config(config, context)
    assert result["summary"] == "Build failed: main"
    assert result["description"] == "Log: FAILURE"


def test_raises_on_missing_var():
    context = {"input": {}, "steps": {}}
    with pytest.raises(ValueError, match="not found"):
        interpolate_variables("Value: {{input.missing_key}}", context)
