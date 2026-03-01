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

variable "node_count" {
  type    = number
  default = 1
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
}
                                     