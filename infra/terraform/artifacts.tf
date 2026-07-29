resource "google_artifact_registry_repository" "application" {
  project       = var.project_id
  location      = var.region
  repository_id = "${local.name_prefix}-images"
  description   = "Immutable development container images for the RAG support chatbot."
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [
    google_project_service.required["artifactregistry.googleapis.com"],
  ]
}
