locals {
  application = "rag-support-chatbot"
  name_prefix = "rag-${var.environment}"

  labels = {
    application = local.application
    environment = var.environment
    managed_by  = "terraform"
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
    "cloudtasks.googleapis.com",
  ])

  runtime_service_accounts = {
    admin = {
      display_name = "RAG admin development runtime"
      description  = "Runtime identity for the development admin portal."
    }
    api = {
      display_name = "RAG API development runtime"
      description  = "Runtime identity for the development public and admin API."
    }
    migration = {
      display_name = "RAG database migration runtime"
      description  = "Passwordless one-shot identity for development database migrations."
    }
    worker = {
      display_name = "RAG worker development runtime"
      description  = "Runtime identity for development ingestion workers."
    }
  }

  runtime_project_roles = {
    admin = toset([
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ])
    api = toset([
      "roles/cloudsql.client",
      "roles/cloudsql.instanceUser",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ])
    migration = toset([
      "roles/cloudsql.client",
      "roles/cloudsql.instanceUser",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ])
    worker = toset([
      "roles/cloudsql.client",
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
    ])
  }

  runtime_project_role_bindings = flatten([
    for service, roles in local.runtime_project_roles : [
      for role in roles : {
        key     = "${service}-${replace(role, "/", "-")}"
        service = service
        role    = role
      }
    ]
  ])

  secret_access = {
    api    = var.secret_names
    worker = toset(["model-provider-api-key"])
  }

  secret_access_bindings = flatten([
    for service, secrets in local.secret_access : [
      for secret in secrets : {
        key     = "${service}-${secret}"
        service = service
        secret  = secret
      }
    ]
  ])

  github_repository_parts         = split("/", var.github_repository)
  github_immutable_subject_prefix = "repo:${local.github_repository_parts[0]}@${var.github_repository_owner_id}/${local.github_repository_parts[1]}@${var.github_repository_id}"
  github_federation_subjects = {
    deployer  = "${local.github_immutable_subject_prefix}:environment:development"
    publisher = "${local.github_immutable_subject_prefix}:ref:refs/heads/main"
  }

  cloud_run_services = {
    admin = {
      ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
      public  = false
    }
    api = {
      ingress = "INGRESS_TRAFFIC_ALL"
      public  = true
    }
    worker = {
      ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      public  = false
    }
  }
}
