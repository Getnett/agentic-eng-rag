resource "google_secret_manager_secret" "application" {
  for_each = var.secret_names

  project   = var.project_id
  secret_id = "${local.name_prefix}-${each.value}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [
    google_project_service.required["secretmanager.googleapis.com"],
  ]
}
