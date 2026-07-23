resource "google_storage_bucket" "raw_sources" {
  name                        = "${var.project_id}-${local.name_prefix}-raw-sources"
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  force_destroy               = var.allow_destructive_cleanup
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  lifecycle_rule {
    condition {
      age                   = 30
      num_newer_versions    = 3
      with_state            = "ARCHIVED"
      matches_storage_class = ["STANDARD"]
    }

    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required["storage.googleapis.com"]]
}
