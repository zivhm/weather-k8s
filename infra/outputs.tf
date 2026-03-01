output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "location" {
  value = var.cluster_location
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --zone ${var.cluster_location} --project ${var.project_id}"
}