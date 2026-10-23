resource "google_compute_network" "app" {
  name                            = "pg-hackathon"
  auto_create_subnetworks         = false
  delete_default_routes_on_create = false
  lifecycle { prevent_destroy = true }
}

resource "google_compute_subnetwork" "vm" {
  name                     = "pg-vm"
  region                   = var.region
  network                  = google_compute_network.app.id
  ip_cidr_range            = "10.73.0.0/28"
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.1
    metadata             = "EXCLUDE_ALL_METADATA"
  }
  lifecycle { prevent_destroy = true }
}

resource "google_compute_subnetwork" "edge" {
  name                     = "pg-edge"
  region                   = var.region
  network                  = google_compute_network.app.id
  ip_cidr_range            = "10.73.1.0/26"
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.1
    metadata             = "EXCLUDE_ALL_METADATA"
  }
  lifecycle { prevent_destroy = true }
}

resource "google_compute_subnetwork" "preview" {
  name                     = "pg-preview"
  region                   = var.region
  network                  = google_compute_network.app.id
  ip_cidr_range            = "10.73.2.0/26"
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.1
    metadata             = "EXCLUDE_ALL_METADATA"
  }
  lifecycle { prevent_destroy = true }
}

resource "google_service_account" "vm" {
  account_id   = "pg-vm-sa"
  display_name = "PharmaGuard VM runtime; no deployment or ingestion permissions"
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(["roles/cloudsql.client", "roles/aiplatform.user", "roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = var.runtime_secret_ids
  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_artifact_registry_repository_iam_member" "images" {
  project    = var.project_id
  location   = var.region
  repository = "pharmaguard-hackathon"
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_compute_firewall" "edge" {
  name          = "pg-web-from-cloud-run"
  network       = google_compute_network.app.name
  source_ranges = [google_compute_subnetwork.edge.ip_cidr_range]
  target_tags   = ["pg-vm"]
  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
  log_config { metadata = "EXCLUDE_ALL_METADATA" }
}

resource "google_compute_firewall" "iap" {
  name          = "pg-ssh-via-iap"
  network       = google_compute_network.app.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["pg-vm"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  log_config { metadata = "EXCLUDE_ALL_METADATA" }
}

resource "google_compute_firewall" "preview" {
  name          = "pg-staging-from-preview"
  network       = google_compute_network.app.name
  source_ranges = [google_compute_subnetwork.preview.ip_cidr_range]
  target_tags   = ["pg-vm"]
  allow {
    protocol = "tcp"
    ports    = ["8081"]
  }
  log_config { metadata = "EXCLUDE_ALL_METADATA" }
}

resource "google_compute_instance" "app" {
  name                      = "pharmaguard-hackathon"
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  deletion_protection       = true
  tags                      = ["pg-vm"]
  labels                    = { app = "pharmaguard", environment = "production", expires = "2026-11-19" }
  boot_disk {
    auto_delete = false
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
      type  = "pd-balanced"
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.vm.id
    network_ip = "10.73.0.2"
    # Outbound registry/Qdrant access; no firewall permits public application ingress.
    access_config {}
  }
  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    startup-script = replace(templatefile("${path.module}/startup.sh.tftpl", {
      expires_at     = var.expires_at
      release_script = filebase64("${path.module}/../../../vm/release.py")
    }), "\r\n", "\n")
  }
  lifecycle { prevent_destroy = true }
}

output "instance_name" {
  description = "Retained application instance name."
  value       = google_compute_instance.app.name
}
output "internal_ip" {
  description = "Private VM address; no public application listener."
  value       = google_compute_instance.app.network_interface[0].network_ip
}
output "network" {
  description = "Existing application VPC name."
  value       = google_compute_network.app.name
}
output "edge_subnet" {
  description = "Production HTTPS edge source subnet."
  value       = google_compute_subnetwork.edge.name
}
