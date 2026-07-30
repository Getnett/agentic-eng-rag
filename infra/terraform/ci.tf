resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${local.name_prefix}-github"
  display_name              = "RAG GitHub Actions"
  description               = "Keyless GitHub Actions identities for RAG development delivery."

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "RAG GitHub OIDC"
  description                        = "Trusts only the immutable GitHub repository and owner IDs."

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }

  attribute_condition = join(" && ", [
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_repository_owner_id}'",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "automation" {
  for_each = {
    deployer  = "Approval-gated GitHub Actions identity for development deployments."
    publisher = "Main-branch GitHub Actions identity for immutable image publication."
  }

  project      = var.project_id
  account_id   = "${local.name_prefix}-ci-${each.key}"
  display_name = "RAG CI ${each.key}"
  description  = each.value

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_service_account_iam_member" "github_federation" {
  for_each = local.github_federation_subjects

  service_account_id = google_service_account.automation[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/${each.value}"
}

resource "google_artifact_registry_repository_iam_member" "automation" {
  for_each = {
    deployer  = "roles/artifactregistry.reader"
    publisher = "roles/artifactregistry.writer"
  }

  project    = var.project_id
  location   = google_artifact_registry_repository.application.location
  repository = google_artifact_registry_repository.application.repository_id
  role       = each.value
  member     = "serviceAccount:${google_service_account.automation[each.key].email}"
}

resource "google_cloud_run_v2_service_iam_member" "automation_deployer" {
  project  = var.project_id
  location = google_cloud_run_v2_service.runtime["api"].location
  name     = google_cloud_run_v2_service.runtime["api"].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.automation["deployer"].email}"
}

resource "google_cloud_run_v2_job_iam_member" "automation_deployer" {
  count = var.migration_image == null ? 0 : 1

  project  = var.project_id
  location = google_cloud_run_v2_job.migration[0].location
  name     = google_cloud_run_v2_job.migration[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.automation["deployer"].email}"
}

resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = toset(["api", "migration"])

  service_account_id = google_service_account.runtime[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.automation["deployer"].email}"
}
