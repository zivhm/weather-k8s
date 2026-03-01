# configure gcp provider
provider "google" {
  project = var.project_id
  region  = var.region
}

# create vpc and subnet                                              
resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
}
resource "google_compute_subnetwork" "subnet" {
  name          = "${var.cluster_name}-subnet"
  ip_cidr_range = "10.10.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id
}

# create cluster
resource "google_container_cluster" "primary" {
  name                     = var.cluster_name
  location                 = var.cluster_location
  network                  = google_compute_network.vpc.id
  subnetwork               = google_compute_subnetwork.subnet.id
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false
  ip_allocation_policy {}
}

# create managed node pool
resource "google_container_node_pool" "primary_nodes" {
  name       = "${var.cluster_name}-np"
  location   = var.cluster_location
  cluster    = google_container_cluster.primary.name
  node_count = var.node_count
  node_config {
    machine_type = var.machine_type
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    labels = {
      workload = "weather"
    }
  }
}