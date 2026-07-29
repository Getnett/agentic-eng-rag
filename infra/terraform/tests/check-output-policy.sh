#!/bin/sh
set -eu

terraform_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
outputs_file="$terraform_dir/outputs.tf"

expected_outputs=$(
  printf '%s\n' \
    artifact_registry_repository_url \
    cloud_run_service_uris \
    cloud_sql_instance_connection_name \
    cloud_tasks_queue_name \
    migration_job_name \
    project_id \
    raw_sources_bucket_name \
    region \
    runtime_service_account_emails \
    secret_manager_secret_ids
)

actual_outputs=$(
  sed -n 's/^output "\([^"]*\)" {.*/\1/p' "$outputs_file" | LC_ALL=C sort
)

if [ "$actual_outputs" != "$expected_outputs" ]; then
  echo "Terraform outputs differ from the approved non-secret identifier allowlist." >&2
  echo "Expected:" >&2
  echo "$expected_outputs" >&2
  echo "Actual:" >&2
  echo "$actual_outputs" >&2
  exit 1
fi

if grep -R -n \
  --include='*.tf' \
  -E 'secret_data[[:space:]]*=|secret_payload[[:space:]]*=|password[[:space:]]*=' \
  "$terraform_dir"; then
  echo "Terraform must not manage secret payloads or passwords." >&2
  exit 1
fi

echo "Terraform output policy passed: approved non-secret identifiers only."
