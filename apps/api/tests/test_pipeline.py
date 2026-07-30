from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict[str, Any]:
    with (WORKFLOWS / name).open(encoding="utf-8") as workflow_file:
        workflow = yaml.safe_load(workflow_file)
    assert isinstance(workflow, dict)
    return workflow


def workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 treats the GitHub Actions `on` key as boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def step_names(job: dict[str, Any]) -> list[str]:
    return [step["name"] for step in job["steps"]]


def test_pull_requests_run_the_locked_repository_gate() -> None:
    workflow = load_workflow("quality.yml")

    assert "pull_request" in workflow_triggers(workflow)
    check_job = workflow["jobs"]["check"]
    assert "Install locked dependencies" in step_names(check_job)
    assert "Run all quality gates" in step_names(check_job)

    with (REPOSITORY_ROOT / "mise.toml").open("rb") as config_file:
        tasks = tomllib.load(config_file)["tasks"]
    assert "test:terraform" in tasks["test"]["depends"]


def test_main_publication_builds_images_after_verification() -> None:
    workflow = load_workflow("publish-images.yml")
    triggers = workflow_triggers(workflow)

    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish"]["needs"] == "verify"
    publish_job = workflow["jobs"]["publish"]
    assert publish_job["permissions"] == {"contents": "read", "id-token": "write"}
    names = step_names(publish_job)
    assert names.index("Authenticate to Google Cloud") < names.index(
        "Publish or reuse commit images"
    )
    assert "Retain image manifest" in names

    publish_step = next(
        step for step in publish_job["steps"] if step["name"] == "Publish or reuse commit images"
    )
    publish_source = publish_step["run"]
    assert "for attempt in 1 2 3" in publish_source
    assert "grep -Fq 'NOT_FOUND:'" in publish_source
    assert 'case "${api_lookup_status}" in' in publish_source
    assert 'case "${migration_lookup_status}" in' in publish_source
    assert 'exit "${api_lookup_status}"' in publish_source
    assert 'exit "${migration_lookup_status}"' in publish_source
    assert publish_source.count("lookup_image_digest") == 5
    assert publish_source.count("verify_image_digest") == 5


def test_development_deployment_is_approval_gated_and_smoke_tested() -> None:
    workflow_path = WORKFLOWS / "deploy-development.yml"
    workflow = load_workflow(workflow_path.name)

    assert "workflow_dispatch" in workflow_triggers(workflow)
    assert workflow["permissions"] == {"contents": "read"}
    deploy_job = workflow["jobs"]["deploy"]
    assert deploy_job["permissions"] == {"contents": "read", "id-token": "write"}
    assert deploy_job["environment"]["name"] == "development"
    names = step_names(deploy_job)
    assert names.index("Run database migrations") < names.index("Deploy health-only API")
    assert names.index("Deploy health-only API") < names.index(
        "Smoke test deployed health endpoint"
    )
    assert "Record deployment metadata" in names
    assert "Retain deployment evidence" in names

    workflow_source = workflow_path.read_text(encoding="utf-8")
    assert "secrets." not in workflow_source
    assert "credentials_json" not in workflow_source
    assert "service_account_key" not in workflow_source
