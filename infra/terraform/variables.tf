variable "project_id" {
  description = "Billed GCP project dedicated to the development environment."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "region" {
  description = "GCP region for regional development resources."
  type        = string
  default     = "europe-west1"
}

variable "vertex_generation_model" {
  description = "Vertex Gemini model ID used by the development generation adapter."
  type        = string
  default     = "gemini-2.5-flash-lite"

  validation {
    condition = (
      length(trimspace(var.vertex_generation_model)) > 0 &&
      !strcontains(var.vertex_generation_model, " ")
    )
    error_message = "vertex_generation_model must be a nonblank model ID without spaces."
  }
}

variable "vertex_generation_input_cost_per_million_tokens_usd" {
  description = "Estimated standard Vertex input price in USD per million tokens for the configured generation model."
  type        = number
  default     = 0.10

  validation {
    condition     = var.vertex_generation_input_cost_per_million_tokens_usd >= 0
    error_message = "vertex_generation_input_cost_per_million_tokens_usd must be non-negative."
  }
}

variable "vertex_generation_output_cost_per_million_tokens_usd" {
  description = "Estimated standard Vertex output price in USD per million tokens for the configured generation model."
  type        = number
  default     = 0.40

  validation {
    condition     = var.vertex_generation_output_cost_per_million_tokens_usd >= 0
    error_message = "vertex_generation_output_cost_per_million_tokens_usd must be non-negative."
  }
}

variable "vertex_embedding_model" {
  description = "Vertex text-embedding model ID shared by document and query embeddings."
  type        = string
  default     = "text-embedding-005"

  validation {
    condition = (
      length(trimspace(var.vertex_embedding_model)) > 0 &&
      !strcontains(var.vertex_embedding_model, " ")
    )
    error_message = "vertex_embedding_model must be a nonblank model ID without spaces."
  }
}

variable "vertex_embedding_dimension" {
  description = "Vector dimension shared by document, query, and pgvector persistence."
  type        = number
  default     = 768

  validation {
    condition     = var.vertex_embedding_dimension > 0 && floor(var.vertex_embedding_dimension) == var.vertex_embedding_dimension
    error_message = "vertex_embedding_dimension must be a positive integer."
  }
}

variable "vertex_embedding_batch_size" {
  description = "Maximum texts sent in one online Vertex embedding request."
  type        = number
  default     = 5

  validation {
    condition     = var.vertex_embedding_batch_size >= 1 && var.vertex_embedding_batch_size <= 5 && floor(var.vertex_embedding_batch_size) == var.vertex_embedding_batch_size
    error_message = "vertex_embedding_batch_size must be an integer between 1 and Vertex's online limit of 5."
  }
}

variable "vertex_embedding_max_attempts" {
  description = "Maximum attempts for one idempotent embedding batch, including the initial call."
  type        = number
  default     = 3

  validation {
    condition     = var.vertex_embedding_max_attempts > 0 && floor(var.vertex_embedding_max_attempts) == var.vertex_embedding_max_attempts
    error_message = "vertex_embedding_max_attempts must be a positive integer."
  }
}

variable "vertex_embedding_initial_retry_delay_seconds" {
  description = "Initial delay before retrying a transient Vertex embedding failure."
  type        = number
  default     = 0.25

  validation {
    condition     = var.vertex_embedding_initial_retry_delay_seconds >= 0
    error_message = "vertex_embedding_initial_retry_delay_seconds must be non-negative."
  }
}

variable "vertex_embedding_max_retry_delay_seconds" {
  description = "Maximum delay between transient Vertex embedding retry attempts."
  type        = number
  default     = 2

  validation {
    condition     = var.vertex_embedding_max_retry_delay_seconds >= var.vertex_embedding_initial_retry_delay_seconds
    error_message = "vertex_embedding_max_retry_delay_seconds must be at least the initial delay."
  }
}

variable "vertex_embedding_input_cost_per_million_characters_usd" {
  description = "Estimated Vertex embedding input price in USD per million input characters."
  type        = number
  default     = 0.025

  validation {
    condition     = var.vertex_embedding_input_cost_per_million_characters_usd >= 0
    error_message = "vertex_embedding_input_cost_per_million_characters_usd must be non-negative."
  }
}

variable "environment" {
  description = "Environment label. The current Terraform root provisions development only."
  type        = string
  default     = "dev"

  validation {
    condition     = var.environment == "dev"
    error_message = "This Terraform root may provision only the dev environment."
  }
}

variable "serverless_subnet_cidr" {
  description = "RFC1918 range used by Cloud Run direct VPC egress."
  type        = string
  default     = "10.20.0.0/24"
}

variable "private_service_prefix_length" {
  description = "Prefix length reserved for private managed-service networking."
  type        = number
  default     = 16

  validation {
    condition     = var.private_service_prefix_length >= 16 && var.private_service_prefix_length <= 24
    error_message = "private_service_prefix_length must be between 16 and 24."
  }
}

variable "database_version" {
  description = "Cloud SQL PostgreSQL major version."
  type        = string
  default     = "POSTGRES_16"
}

variable "database_tier" {
  description = "Cloud SQL machine tier for development."
  type        = string
  default     = "db-f1-micro"
}

variable "database_name" {
  description = "Initial non-secret application database name."
  type        = string
  default     = "support_rag"
}

variable "cloud_run_smoke_image" {
  description = "Public infrastructure smoke image; application deployment replaces it later."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"

  validation {
    condition     = startswith(var.cloud_run_smoke_image, "us-docker.pkg.dev/cloudrun/container/hello")
    error_message = "POR-32 permits only the documented Google Cloud Run smoke image."
  }
}

variable "migration_image" {
  description = "Optional immutable Artifact Registry digest for the one-shot migration job."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.migration_image == null ||
      can(regex(
        "^[-a-z0-9.]+/[-a-z0-9_/]+@sha256:[0-9a-f]{64}$",
        var.migration_image,
      ))
    )
    error_message = "migration_image must be null or an immutable image reference ending in @sha256:<64 lowercase hex characters>."
  }
}

variable "github_repository" {
  description = "GitHub owner/repository allowed to federate into the development project."
  type        = string
  default     = "Getnett/agentic-eng-rag"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use the owner/repository form."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID used in the OIDC trust condition."
  type        = string
  default     = "1308771373"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must contain only decimal digits."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub owner ID used in the OIDC trust condition."
  type        = string
  default     = "24660273"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must contain only decimal digits."
  }
}

variable "deletion_protection" {
  description = "Protect Cloud SQL and Cloud Run from accidental deletion."
  type        = bool
  default     = true
}

variable "allow_destructive_cleanup" {
  description = "Allow Terraform to delete non-empty development buckets during an intentional destroy."
  type        = bool
  default     = false
}

variable "secret_names" {
  description = "Names of empty Secret Manager containers. Values are never managed by this root."
  type        = set(string)
  default = [
    "application-auth-secret",
    "model-provider-api-key",
  ]

  validation {
    condition = (
      contains(var.secret_names, "application-auth-secret") &&
      contains(var.secret_names, "model-provider-api-key") &&
      alltrue([for name in var.secret_names : can(regex("^[a-z][a-z0-9-]{0,253}[a-z0-9]$", name))])
    )
    error_message = "secret_names must contain application-auth-secret and model-provider-api-key, using only valid Secret Manager secret IDs."
  }
}

variable "supabase_auth_secret_version" {
  description = "Optional immutable numeric version of the application-auth-secret payload mounted by the API."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.supabase_auth_secret_version == null ||
      can(regex("^[1-9][0-9]*$", var.supabase_auth_secret_version))
    )
    error_message = "supabase_auth_secret_version must be null or an immutable positive numeric Secret Manager version."
  }
}
