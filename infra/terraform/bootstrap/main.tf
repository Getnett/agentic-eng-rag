locals {
  labels = {
    application = "rag-support-chatbot"
    environment = "dev"
    managed_by  = "terraform"
    purpose     = "remote-state"
  }
}

resource "google_project_service" "storage" {
  project            = var.project_id
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "terraform_state" {
  name                        = var.state_bucket_name
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  force_destroy               = var.allow_state_bucket_destroy
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 2592000
  }

  depends_on = [google_project_service.storage]
}
