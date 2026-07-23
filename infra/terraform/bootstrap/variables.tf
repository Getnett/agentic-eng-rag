variable "project_id" {
  description = "Billed GCP development project that owns the state bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "region" {
  description = "GCP region for the state bucket."
  type        = string
  default     = "us-central1"
}

variable "state_bucket_name" {
  description = "Globally unique GCS bucket name used by the development backend."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid GCS bucket name."
  }
}

variable "allow_state_bucket_destroy" {
  description = "Allow intentional deletion of a non-empty state bucket after the main environment is gone."
  type        = bool
  default     = false
}
