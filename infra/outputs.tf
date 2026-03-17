output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "location" {
  value = var.cluster_location
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.weather.repository_id
}

output "weather_image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.weather.repository_id}/weather-app"
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --zone ${var.cluster_location} --project ${var.project_id}"
}
