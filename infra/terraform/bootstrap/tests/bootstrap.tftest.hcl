mock_provider "google" {}

variables {
  project_id        = "rag-dev-example"
  state_bucket_name = "rag-dev-example-tfstate"
}

run "remote_state_plan" {
  command = plan

  assert {
    condition     = google_storage_bucket.terraform_state.uniform_bucket_level_access
    error_message = "The remote-state bucket must enforce uniform bucket-level access."
  }

  assert {
    condition     = google_storage_bucket.terraform_state.public_access_prevention == "enforced"
    error_message = "The remote-state bucket must enforce public-access prevention."
  }

  assert {
    condition     = google_storage_bucket.terraform_state.versioning[0].enabled
    error_message = "The remote-state bucket must retain object versions."
  }

  assert {
    condition     = google_storage_bucket.terraform_state.retention_policy[0].retention_period >= 2592000
    error_message = "Remote state must be retained for at least 30 days."
  }

  assert {
    condition = alltrue([
      for key, value in local.labels :
      lookup(google_storage_bucket.terraform_state.labels, key, null) == value
    ])
    error_message = "The remote-state bucket must receive development and ownership labels."
  }
}
