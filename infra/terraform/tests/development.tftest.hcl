mock_provider "google" {}

variables {
  project_id = "rag-dev-example"
}

run "development_plan" {
  command = plan

  assert {
    condition     = google_storage_bucket.raw_sources.uniform_bucket_level_access
    error_message = "The raw-source bucket must enforce uniform bucket-level access."
  }

  assert {
    condition     = google_storage_bucket.raw_sources.public_access_prevention == "enforced"
    error_message = "The raw-source bucket must enforce public-access prevention."
  }

  assert {
    condition     = google_storage_bucket.raw_sources.versioning[0].enabled
    error_message = "The raw-source bucket must retain object versions."
  }

  assert {
    condition     = google_sql_database_instance.primary.settings[0].ip_configuration[0].ipv4_enabled == false
    error_message = "Cloud SQL must not expose a public IPv4 address."
  }

  assert {
    condition = length([
      for flag in google_sql_database_instance.primary.settings[0].database_flags :
      flag if flag.name == "cloudsql.iam_authentication" && flag.value == "on"
    ]) == 1
    error_message = "Cloud SQL must enable IAM database authentication."
  }

  assert {
    condition     = google_sql_database_instance.primary.deletion_protection && google_sql_database_instance.primary.settings[0].deletion_protection_enabled
    error_message = "Cloud SQL must enable both Terraform and GCP API deletion protection."
  }

  assert {
    condition     = google_sql_database_instance.primary.settings[0].final_backup_config[0].enabled == false
    error_message = "The disposable development database must not retain a final backup after intentional deletion."
  }

  assert {
    condition     = google_service_account.runtime["api"].account_id != google_service_account.runtime["worker"].account_id
    error_message = "API and worker must use separate service accounts."
  }

  assert {
    condition = (
      google_artifact_registry_repository.application.docker_config[0].immutable_tags &&
      google_artifact_registry_repository_iam_member.automation["publisher"].role == "roles/artifactregistry.writer" &&
      google_artifact_registry_repository_iam_member.automation["deployer"].role == "roles/artifactregistry.reader"
    )
    error_message = "Published images must use immutable tags and narrowly scoped repository access."
  }

  assert {
    condition = (
      google_iam_workload_identity_pool_provider.github.oidc[0].issuer_uri == "https://token.actions.githubusercontent.com" &&
      google_iam_workload_identity_pool_provider.github.attribute_mapping["google.subject"] == "assertion.sub" &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, var.github_repository_id) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, var.github_repository_owner_id)
    )
    error_message = "GitHub OIDC trust must use the official issuer and immutable repository and owner IDs."
  }

  assert {
    condition = (
      local.github_federation_subjects["publisher"] == "repo:${var.github_repository}:ref:refs/heads/main" &&
      local.github_federation_subjects["deployer"] == "repo:${var.github_repository}:environment:development"
    )
    error_message = "Publisher and deployer impersonation must be restricted to main and the approved environment subjects."
  }

  assert {
    condition = (
      google_cloud_run_v2_service_iam_member.automation_deployer.role == "roles/run.developer" &&
      google_cloud_run_v2_service_iam_member.automation_deployer.name == google_cloud_run_v2_service.runtime["api"].name &&
      toset(keys(google_service_account_iam_member.deployer_act_as)) == toset(["api", "migration"]) &&
      alltrue([
        for binding in google_service_account_iam_member.deployer_act_as :
        binding.role == "roles/iam.serviceAccountUser"
      ])
    )
    error_message = "The deployment identity may update only the API and act only as the API and migration runtimes."
  }

  assert {
    condition = (
      google_cloud_run_v2_service.runtime["api"].ingress == "INGRESS_TRAFFIC_ALL" &&
      google_cloud_run_v2_service.runtime["api"].invoker_iam_disabled &&
      !google_cloud_run_v2_service.runtime["admin"].invoker_iam_disabled &&
      !google_cloud_run_v2_service.runtime["worker"].invoker_iam_disabled
    )
    error_message = "Only the health-only API service may accept unauthenticated public traffic."
  }

  assert {
    condition = (
      google_service_account.runtime["migration"].account_id != google_service_account.runtime["api"].account_id &&
      contains(local.runtime_project_roles["migration"], "roles/cloudsql.client") &&
      contains(local.runtime_project_roles["migration"], "roles/cloudsql.instanceUser")
    )
    error_message = "Migrations must use a dedicated passwordless Cloud SQL identity."
  }

  assert {
    condition = (
      google_sql_user.migration.type == "CLOUD_IAM_SERVICE_ACCOUNT" &&
      google_sql_user.migration.database_roles == tolist(["cloudsqlsuperuser"]) &&
      length("${local.name_prefix}-migration@${var.project_id}.iam") <= 63
    )
    error_message = "The migration database user must use IAM, fit PostgreSQL's identifier limit, and have only the extension-management role."
  }

  assert {
    condition = alltrue([
      for roles in values(local.runtime_project_roles) :
      !contains(roles, "roles/owner") && !contains(roles, "roles/editor")
    ])
    error_message = "Runtime service accounts must not receive primitive Owner or Editor roles."
  }

  assert {
    condition     = google_cloud_tasks_queue_iam_member.api_enqueuer.role == "roles/cloudtasks.enqueuer"
    error_message = "The API runtime must receive queue-scoped enqueue access."
  }

  assert {
    condition     = google_storage_bucket_iam_member.runtime["api"].role == "roles/storage.objectAdmin" && google_storage_bucket_iam_member.runtime["worker"].role == "roles/storage.objectViewer"
    error_message = "Bucket-scoped permissions must reflect the API upload and worker read boundaries."
  }

  assert {
    condition     = alltrue([for binding in google_secret_manager_secret_iam_member.runtime : binding.role == "roles/secretmanager.secretAccessor"])
    error_message = "Secret access must be scoped to the managed secret containers."
  }

  assert {
    condition = alltrue([
      for roles in values(local.runtime_project_roles) :
      !contains(roles, "roles/storage.admin") &&
      !contains(roles, "roles/storage.objectAdmin") &&
      !contains(roles, "roles/secretmanager.secretAccessor") &&
      !contains(roles, "roles/cloudtasks.enqueuer")
    ])
    error_message = "Resource-scoped permissions must not be broadened to the project."
  }

  assert {
    condition = alltrue(concat(
      [
        for service in google_cloud_run_v2_service.runtime :
        alltrue([for key, value in local.labels : lookup(service.labels, key, null) == value])
      ],
      [
        alltrue([
          for key, value in local.labels :
          lookup(google_sql_database_instance.primary.settings[0].user_labels, key, null) == value
        ])
      ],
      [
        alltrue([
          for key, value in local.labels :
          lookup(google_storage_bucket.raw_sources.labels, key, null) == value
        ])
      ],
      [
        alltrue([
          for key, value in local.labels :
          lookup(google_artifact_registry_repository.application.labels, key, null) == value
        ])
      ],
      [
        for secret in google_secret_manager_secret.application :
        alltrue([for key, value in local.labels : lookup(secret.labels, key, null) == value])
      ],
    ))
    error_message = "All label-capable development resources must receive the standard labels."
  }

  assert {
    condition     = length(google_secret_manager_secret.application) == length(var.secret_names)
    error_message = "Terraform should create secret containers without secret payload resources."
  }
}

run "migration_job_plan" {
  command = plan

  variables {
    migration_image = "europe-west1-docker.pkg.dev/rag-dev-example/rag-dev-images/migrations@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition = (
      google_cloud_run_v2_job_iam_member.automation_deployer[0].role == "roles/run.developer" &&
      google_cloud_run_v2_job_iam_member.automation_deployer[0].name == google_cloud_run_v2_job.migration[0].name
    )
    error_message = "The deployment identity may update only the managed migration job."
  }

  assert {
    condition = (
      google_cloud_run_v2_job.migration[0].template[0].task_count == 1 &&
      google_cloud_run_v2_job.migration[0].template[0].template[0].max_retries == 0
    )
    error_message = "The migration job must execute once without automatic retries."
  }

  assert {
    condition     = google_cloud_run_v2_job.migration[0].template[0].template[0].vpc_access[0].egress == "PRIVATE_RANGES_ONLY"
    error_message = "The migration job must use private VPC egress."
  }

  assert {
    condition = startswith(
      google_cloud_run_v2_job.migration[0].template[0].template[0].containers[0].image,
      "europe-west1-docker.pkg.dev/rag-dev-example/rag-dev-images/migrations@sha256:",
    )
    error_message = "The migration job must use an immutable image from the managed repository."
  }
}
