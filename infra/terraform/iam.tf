resource "google_service_account" "runtime" {
  for_each = local.runtime_service_accounts

  project      = var.project_id
  account_id   = "${local.name_prefix}-${each.key}"
  display_name = each.value.display_name
  description  = each.value.description

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_project_iam_member" "runtime" {
  for_each = {
    for binding in local.runtime_project_role_bindings : binding.key => binding
  }

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.runtime[each.value.service].email}"
}

resource "google_storage_bucket_iam_member" "runtime" {
  for_each = {
    api    = "roles/storage.objectAdmin"
    worker = "roles/storage.objectViewer"
  }

  bucket = google_storage_bucket.raw_sources.name
  role   = each.value
  member = "serviceAccount:${google_service_account.runtime[each.key].email}"
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each = {
    for binding in local.secret_access_bindings : binding.key => binding
  }

  project   = var.project_id
  secret_id = google_secret_manager_secret.application[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value.service].email}"
}

resource "google_cloud_tasks_queue_iam_member" "api_enqueuer" {
  project  = var.project_id
  location = google_cloud_tasks_queue.ingestion.location
  name     = google_cloud_tasks_queue.ingestion.name
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.runtime["api"].email}"
}
