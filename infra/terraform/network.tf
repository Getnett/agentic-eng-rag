resource "google_compute_network" "development" {
  name                    = "${local.name_prefix}-network"
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required["compute.googleapis.com"]]
}

resource "google_compute_subnetwork" "serverless" {
  name                     = "${local.name_prefix}-serverless"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.development.id
  ip_cidr_range            = var.serverless_subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_global_address" "private_services" {
  name          = "${local.name_prefix}-private-services"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_prefix_length
  network       = google_compute_network.development.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.development.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [
    google_project_service.required["servicenetworking.googleapis.com"],
  ]
}
