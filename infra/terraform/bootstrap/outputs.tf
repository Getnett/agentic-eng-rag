output "state_bucket_name" {
  description = "Remote-state bucket identifier."
  value       = google_storage_bucket.terraform_state.name
}
