# Task: Weather App on Kubernetes (Terraform + CI/CD)

This task is to prove you can set up a small "production-like" platform end-to-end:

- Use Terraform to create a Kubernetes cluster.
- Deploy a simple weather app with a proper release flow.

You’ll build and push the app’s Docker image in CI, deploy it automatically with CD, and add core operational pieces:

- Monitoring (Prometheus/Grafana)
- Autoscaling (KEDA)
- Centralized logging (Elastic/Kibana)

The result should be fully reproducible from a public Git repo with clear documentation, so someone else can spin it up, observe it, and tear it down safely.

## Deliverables

- Create a public GitHub repo and structure it clearly for:
  - `infra/` (Terraform)
  - `apps/` (weather app)
  - `.github/workflows/` (CI/CD)
- Using Terraform, provision a Kubernetes cluster (prefer managed: EKS/GKE/AKS), including networking and node group(s), with clean outputs and destroy instructions.
- Deploy a simple weather web app to the cluster (Deployment, Service, Ingress/LoadBalancer), with readiness/liveness probes and resource requests/limits.
- Add a Dockerfile for the app and make the app configurable via env vars/ConfigMap (API key via Secret).
- Create a GitHub Actions CI workflow that builds the Docker image on every PR, and on merge to `main` builds and pushes it to a registry (GHCR is fine) using the commit SHA tag.
- Create a CD workflow that deploys the app to the cluster automatically on `main`, using Helm or Kustomize and the exact image SHA tag (no `latest`).
- Install Prometheus + Grafana (Helm recommended), expose access (Ingress or port-forward steps), and provide at least one dashboard plus one alert rule.
- Install KEDA and configure autoscaling for the weather app (prefer scaling on a Prometheus metric or requests/CPU), and document how to test scaling.
- Install a logging stack (EFK/Elastic: Fluent Bit/Fluentd → Elasticsearch → Kibana) and show how to view the app logs in Kibana.
- Write a solid README with end-to-end steps to provision infra, deploy, access app/monitoring/logging, run CI/CD, and tear everything down.
