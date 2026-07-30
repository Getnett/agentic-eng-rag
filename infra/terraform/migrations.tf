resource "google_cloud_run_v2_job" "migration" {
  count = var.migration_image == null ? 0 : 1

  name                = "${local.name_prefix}-migrate"
  project             = var.project_id
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.labels

  template {
    task_count = 1

    template {
      service_account = google_service_account.runtime["migration"].email
      max_retries     = 0
      timeout         = "600s"

      containers {
        image   = coalesce(var.migration_image, var.cloud_run_smoke_image)
        command = ["python", "-m", "rag_api.migrations"]
        args    = ["upgrade"]

        env {
          name  = "INSTANCE_CONNECTION_NAME"
          value = google_sql_database_instance.primary.connection_name
        }

        env {
          name  = "DB_NAME"
          value = google_sql_database.application.name
        }

        env {
          name = "DB_USER"
          value = trimsuffix(
            google_service_account.runtime["migration"].email,
            ".gserviceaccount.com",
          )
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"

        network_interfaces {
          network    = google_compute_network.development.name
          subnetwork = google_compute_subnetwork.serverless.name
          tags       = ["${local.name_prefix}-migration"]
        }
      }
    }
  }

  lifecycle {
    # Terraform creates the job; the deployment pipeline advances its image digest.
    ignore_changes = [
      client,
      client_version,
      template[0].template[0].containers[0].image,
    ]

    precondition {
      condition = startswith(
        coalesce(var.migration_image, ""),
        "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.application.repository_id}/migrations@sha256:",
      )
      error_message = "migration_image must use the Terraform-managed migrations repository path and an immutable digest."
    }
  }

  depends_on = [
    google_project_iam_member.runtime,
    google_project_service.required["run.googleapis.com"],
    google_service_networking_connection.private_services,
    google_sql_user.migration,
  ]
}
