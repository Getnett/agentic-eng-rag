output "project_id" {
  description = "Development GCP project identifier."
  value       = var.project_id
}

output "region" {
  description = "Development GCP region."
  value       = var.region
}

output "artifact_registry_repository_url" {
  description = "Docker repository URL for immutable development images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.application.repository_id}"
}

output "automation_service_account_emails" {
  description = "Keyless CI publisher and development deployer service-account identifiers."
  value = {
    for purpose, account in google_service_account.automation :
    purpose => account.email
  }
}

output "raw_sources_bucket_name" {
  description = "Private raw-source bucket identifier."
  value       = google_storage_bucket.raw_sources.name
}

output "cloud_sql_instance_connection_name" {
  description = "Cloud SQL connection identifier; this is not a credential."
  value       = google_sql_database_instance.primary.connection_name
}

output "cloud_run_service_uris" {
  description = "Cloud Run service endpoints; each service retains its configured access policy."
  value = {
    for service, resource in google_cloud_run_v2_service.runtime :
    service => resource.uri
  }
}

output "cloud_tasks_queue_name" {
  description = "Cloud Tasks ingestion queue identifier."
  value       = google_cloud_tasks_queue.ingestion.name
}

output "migration_job_name" {
  description = "One-shot migration job name, or null until an immutable image is configured."
  value       = try(google_cloud_run_v2_job.migration[0].name, null)
}

output "github_workload_identity_provider" {
  description = "GitHub Actions workload identity provider resource name."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "runtime_service_account_emails" {
  description = "Runtime service account identifiers."
  value = {
    for service, account in google_service_account.runtime :
    service => account.email
  }
}

output "secret_manager_secret_ids" {
  description = "Secret container identifiers only; no versions or payloads."
  value = {
    for name, secret in google_secret_manager_secret.application :
    name => secret.secret_id
  }
}
