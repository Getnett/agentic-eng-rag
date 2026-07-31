mock_provider "google" {}

variables {
  project_id                   = "rag-dev-example"
  supabase_auth_secret_version = "7"
}

override_resource {
  target          = google_iam_workload_identity_pool.github
  override_during = plan
  values = {
    name = "projects/123456789/locations/global/workloadIdentityPools/rag-dev-github"
  }
}

run "development_plan" {
  command = plan

  assert {
    condition     = google_storage_bucket.raw_sources.uniform_bucket_level_access
    error_message = "The raw-source bucket must enforce uniform bucket-level access."
  }

  assert {
    condition = (
      google_sql_user.api.type == "CLOUD_IAM_SERVICE_ACCOUNT" &&
      contains(local.runtime_project_roles["api"], "roles/cloudsql.client") &&
      contains(local.runtime_project_roles["api"], "roles/cloudsql.instanceUser") &&
      contains(local.runtime_project_roles["api"], "roles/aiplatform.user") &&
      !contains(local.runtime_project_roles["admin"], "roles/aiplatform.user") &&
      !contains(local.runtime_project_roles["migration"], "roles/aiplatform.user") &&
      !contains(local.runtime_project_roles["worker"], "roles/aiplatform.user")
    )
    error_message = "The API must use its own Cloud SQL identity and be the only runtime allowed to invoke Vertex generation."
  }

  assert {
    condition = (
      contains(
        google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env[*].name,
        "INSTANCE_CONNECTION_NAME",
      ) &&
      contains(
        google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env[*].name,
        "DB_NAME",
      ) &&
      contains(
        google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env[*].name,
        "DB_USER",
      ) &&
      one([
        for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
        environment.value == "rag-dev-example"
        if environment.name == "GOOGLE_CLOUD_PROJECT"
      ]) &&
      one([
        for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
        environment.value == "europe-west1"
        if environment.name == "GOOGLE_CLOUD_LOCATION"
      ]) &&
      one([
        for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
        environment.value == "gemini-2.5-flash-lite"
        if environment.name == "VERTEX_GENERATION_MODEL"
      ]) &&
      one([
        for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
        environment.value == "0.1"
        if environment.name == "VERTEX_GENERATION_INPUT_COST_PER_MILLION_TOKENS_USD"
      ]) &&
      one([
        for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
        environment.value == "0.4"
        if environment.name == "VERTEX_GENERATION_OUTPUT_COST_PER_MILLION_TOKENS_USD"
      ])
    )
    error_message = "The API must receive non-secret Cloud SQL and explicit Vertex routing and pricing configuration."
  }

  assert {
    condition = one([
      for environment in google_cloud_run_v2_service.runtime["api"].template[0].containers[0].env :
      environment.value_source[0].secret_key_ref[0].version == "7"
      if environment.name == "SUPABASE_AUTH_CONFIG"
    ])
    error_message = "Supabase verification config must use one immutable Secret Manager version."
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
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_mapping["attribute.delivery_role"], local.github_federation_subjects["publisher"]) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_mapping["attribute.delivery_role"], local.github_federation_subjects["deployer"]) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, var.github_repository_id) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, var.github_repository_owner_id) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, local.github_federation_subjects["publisher"]) &&
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, local.github_federation_subjects["deployer"])
    )
    error_message = "GitHub OIDC trust must derive delivery roles from exact subjects and retain immutable repository and owner IDs."
  }

  assert {
    condition = (
      local.github_immutable_subject_prefix == "repo:Getnett@${var.github_repository_owner_id}/agentic-eng-rag@${var.github_repository_id}" &&
      local.github_federation_subjects["publisher"] == "${local.github_immutable_subject_prefix}:ref:refs/heads/main" &&
      local.github_federation_subjects["deployer"] == "${local.github_immutable_subject_prefix}:environment:development" &&
      google_service_account_iam_member.github_federation["publisher"].member == "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.delivery_role/publisher" &&
      google_service_account_iam_member.github_federation["deployer"].member == "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.delivery_role/deployer"
    )
    error_message = "Publisher and deployer impersonation must use role-specific principal sets derived only from main and the approved environment subjects."
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
    error_message = "The migration database user must use IAM, fit PostgreSQL's identifier limit, and keep only the extension-management role."
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
      google_cloud_run_v2_job.migration[0].template[0].template[0].max_retries == 0 &&
      one([
        for environment in google_cloud_run_v2_job.migration[0].template[0].template[0].containers[0].env :
        environment.name == "APP_DB_USER"
        if environment.name == "APP_DB_USER"
      ])
    )
    error_message = "The migration job must execute once and grant only the configured API database user."
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
