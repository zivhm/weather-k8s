variable "project_id" {
  type    = string
  default = "devops-486417"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "cluster_location" {
  type    = string
  default = "us-central1-a"
}

variable "cluster_name" {
  type    = string
  default = "weather-cluster"
}

variable "artifact_repository" {
  type    = string
  default = "weather"
}

variable "node_count" {
  type    = number
  default = 2
}

variable "min_node_count" {
  type    = number
  default = 2
}

variable "max_node_count" {
  type    = number
  default = 4
}

variable "machine_type" {
  type    = string
  default = "e2-standard-2"
}
