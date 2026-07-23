resource "google_cloud_tasks_queue" "ingestion" {
  name     = "${local.name_prefix}-ingestion"
  project  = var.project_id
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 10
    max_dispatches_per_second = 5
  }

  retry_config {
    max_attempts       = 5
    max_retry_duration = "3600s"
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 5
  }

  depends_on = [
    google_project_service.required["cloudtasks.googleapis.com"],
  ]
}
