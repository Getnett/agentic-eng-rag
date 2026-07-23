output "project_id" {
  description = "Development GCP project identifier."
  value       = var.project_id
}

output "region" {
  description = "Development GCP region."
  value       = var.region
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
  description = "Authenticated Cloud Run service endpoints."
  value = {
    for service, resource in google_cloud_run_v2_service.runtime :
    service => resource.uri
  }
}

output "cloud_tasks_queue_name" {
  description = "Cloud Tasks ingestion queue identifier."
  value       = google_cloud_tasks_queue.ingestion.name
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
