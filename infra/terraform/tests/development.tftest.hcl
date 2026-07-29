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
