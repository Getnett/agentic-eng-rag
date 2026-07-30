resource "google_cloud_run_v2_service" "runtime" {
  for_each = local.cloud_run_services

  name                 = "${local.name_prefix}-${each.key}"
  project              = var.project_id
  location             = var.region
  ingress              = each.value.ingress
  invoker_iam_disabled = each.value.public
  deletion_protection  = var.deletion_protection
  labels               = local.labels

  template {
    service_account = google_service_account.runtime[each.key].email
    labels          = local.labels

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.cloud_run_smoke_image

      env {
        name  = "APP_ENVIRONMENT"
        value = var.environment
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"

      network_interfaces {
        network    = google_compute_network.development.name
        subnetwork = google_compute_subnetwork.serverless.name
        tags       = ["${local.name_prefix}-${each.key}"]
      }
    }
  }

  depends_on = [
    google_project_iam_member.runtime,
    google_project_service.required["run.googleapis.com"],
    google_service_networking_connection.private_services,
  ]

  lifecycle {
    # Terraform owns service configuration; the deployment pipeline owns revisions.
    ignore_changes = [
      client,
      client_version,
      template[0].containers[0].image,
      template[0].revision,
    ]
  }
}
