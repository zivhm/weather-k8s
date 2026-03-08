# Weather App on Kubernetes

Small production-like platform on GKE with Terraform, GitHub Actions CI/CD, Prometheus/Grafana monitoring, KEDA autoscaling, and centralized logging with Fluent Bit, Elasticsearch, and Kibana.

## Repo Layout

- `infra/`: Terraform for VPC, subnet, GKE cluster, and node pool
- `apps/weather/`: Flask weather app, tests, and Dockerfile
- `deploy/k8s/`: base Kubernetes manifests for the app
- `deploy/monitoring/`: Prometheus alert rules
- `deploy/keda/`: KEDA ScaledObject
- `deploy/logging/`: Elasticsearch, Kibana, and Fluent Bit Helm values
- `.github/workflows/`: CI and CD workflows
- `docs/weather-k8s-architecture.drawio`: architecture diagram

## What This Delivers

- Terraform-managed GKE cluster with networking
- Weather app deployed as a Kubernetes `Deployment` and exposed by a `LoadBalancer` `Service`
- GitHub Actions CI that tests and builds on pull requests, then pushes commit-SHA and `stable` tags on `main`/`master`
- GitHub Actions CD that deploys the exact commit SHA after CI succeeds
- Prometheus + Grafana via `kube-prometheus-stack`
- KEDA CPU-based autoscaling for the weather app
- Fluent Bit -> Elasticsearch -> Kibana logging with app logs visible in Kibana Discover

## Prerequisites

- Terraform `>= 1.5`
- `gcloud`
- `kubectl`
- `helm`
- Docker
- A GCP project with billing enabled
- Application Default Credentials for Terraform:

```bash
gcloud auth application-default login
```

- GitHub repository secrets:
  - `GCP_PROJECT_ID`
  - `GCP_SA_KEY`

The service account used by CI/CD needs at least:
- Artifact Registry writer access
- GKE access for deployment

## 1. Provision Infrastructure

Apply Terraform:

```bash
terraform -chdir=infra init
terraform -chdir=infra apply
```

Fetch cluster credentials:

```bash
gcloud container clusters get-credentials weather-cluster --zone us-central1-a --project devops-486417
kubectl get nodes
kubectl top nodes
```

Notes:
- The current defaults are sized to run the full stack, including Elasticsearch and Kibana.
- If you scale node count or machine type down, logging will become the first thing to fail.

## 2. Run the App

Apply the app manifests:

```bash
kubectl apply -f deploy/k8s/
kubectl -n weather rollout status deployment/weather-app
kubectl -n weather get svc
```

The deployment manifest bootstraps from:

```text
us-central1-docker.pkg.dev/devops-486417/weather/weather-app:stable
```

That tag is also published by CI, so a clean cluster can start from the manifest directly.

Access the app:

```bash
kubectl -n weather get svc weather-service
```

Then open:

```text
http://<EXTERNAL-IP>/healthz
http://<EXTERNAL-IP>/weather?city=Berlin
```

## 3. CI/CD Flow

### CI

File: [`.github/workflows/ci.yaml`](.github/workflows/ci.yaml)

- Runs on every pull request
- Installs dependencies
- Syntax checks `app.py`
- Runs `pytest`
- Builds Docker image
- On push to `main` or `master`, pushes:
  - `weather-app:<commit-sha>`
  - `weather-app:stable`

### CD

File: [`.github/workflows/cd.yaml`](.github/workflows/cd.yaml)

- Triggered by successful CI completion using `workflow_run`
- Checks out the exact CI commit SHA
- Applies manifests
- Sets the deployment image to the exact commit SHA
- Waits for rollout and verifies the deployed image

This avoids mutable-tag-only deployment and keeps releases traceable to a specific commit.

## 4. Monitoring

Install Prometheus and Grafana:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring
kubectl apply -f deploy/monitoring/weather-alerts.yaml
kubectl -n monitoring get pods
```

Access Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Open:

```text
http://localhost:3000
```

Get the Grafana admin password:

```bash
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d && echo
```

Alert rule included:
- `WeatherAppNoRunningPods` in [`deploy/monitoring/weather-alerts.yaml`](deploy/monitoring/weather-alerts.yaml)

Dashboard:
- `kube-prometheus-stack` ships with default Kubernetes dashboards in Grafana
- use the workload / cluster dashboards to observe the app and node health

## 5. Autoscaling With KEDA

Install KEDA:

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
kubectl create namespace keda --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install keda kedacore/keda -n keda
kubectl apply -f deploy/keda/scaledobject.yaml
kubectl -n weather get scaledobject,hpa
```

Current scaling config:
- CPU trigger
- threshold: `10%`
- min replicas: `1`
- max replicas: `5`

The low threshold is intentional for easy demonstration because the app itself is lightweight.

### KEDA Validation

Watch replicas and HPA:

```bash
kubectl -n weather get pods -w
```

In another terminal:

```bash
kubectl -n weather get hpa -w
```

Generate load:

```bash
kubectl -n weather run loadgen --rm -it --restart=Never --image=busybox:1.36 --command -- sh -c 'for i in $(seq 1 50); do while true; do wget -q -O- http://weather-service.weather.svc.cluster.local/weather?city=Berlin >/dev/null; done & done; wait'
```

Success criteria:
- HPA target exceeds threshold
- replicas increase
- after stopping the load, replicas scale back down after cooldown

## 6. Centralized Logging

Install logging in strict order.

### Elasticsearch

```bash
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
kubectl apply -f deploy/logging/namespace.yaml
helm upgrade --install weather-logs elastic/elasticsearch -n logging -f deploy/logging/elasticsearch-values.yaml
kubectl -n logging rollout status statefulset/weather-logs-master --timeout=600s
```

### Kibana

```bash
helm upgrade --install kibana elastic/kibana -n logging -f deploy/logging/kibana-values.yaml
kubectl -n logging get pods
```

### Fluent Bit

```bash
helm upgrade --install fluent-bit fluent/fluent-bit -n logging -f deploy/logging/fluent-bit-values.yaml
kubectl -n logging get pods
```

Important implementation details:
- Kibana and Fluent Bit use `weather-logs-master.logging.svc` because it matches Elasticsearch cert SANs
- Elasticsearch readiness is set to `yellow` for the single-node topology
- Elasticsearch memory was increased to avoid `OOMKilled`

## 7. Logging Validation

Check Fluent Bit health:

```bash
kubectl -n logging logs -l app.kubernetes.io/name=fluent-bit --tail=100
```

You should not see repeated `_bulk` `401` errors.

Check Elasticsearch indices:

PowerShell:

```powershell
$p=[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String((kubectl -n logging get secret weather-logs-master-credentials -o jsonpath='{.data.password}')))
kubectl -n logging exec weather-logs-master-0 -- curl -k -u elastic:$p https://localhost:9200/_cat/indices?v
```

Bash:

```bash
kubectl -n logging exec weather-logs-master-0 -- curl -k -u elastic:$(kubectl -n logging get secret weather-logs-master-credentials -o jsonpath="{.data.password}" | base64 -d) https://localhost:9200/_cat/indices?v
```

Access Kibana:

```bash
kubectl -n logging port-forward svc/kibana-kibana 5601:5601
```

Open:

```text
http://localhost:5601
```

Login:
- username: `elastic`
- password:

PowerShell:

```powershell
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String((kubectl -n logging get secret weather-logs-master-credentials -o jsonpath='{.data.password}')))
```

Bash:

```bash
kubectl -n logging get secret weather-logs-master-credentials -o jsonpath="{.data.password}" | base64 -d && echo
```

In Kibana Discover:
- select or create data view `weather-*`
- search:

```text
kubernetes.namespace_name : "weather"
```

Because the app now emits request logs and Gunicorn access logs to stdout, fresh requests to `/weather` will show up clearly.

## 8. Local App Validation

Run tests:

```bash
pytest -q apps/weather/tests
```

Run the app locally:

```bash
python apps/weather/app.py
```

Then:

```text
http://localhost:8080/healthz
http://localhost:8080/weather?city=Berlin
```

## 9. Known Issues / Operational Notes

- Logging is the most resource-sensitive part of the stack.
- If Elasticsearch becomes unstable, Kibana authentication and readiness will also appear broken.
- If fresh logs stop appearing but older logs exist, check Fluent Bit for `_bulk` `401` and restart Fluent Bit:

```bash
kubectl -n logging rollout restart daemonset/fluent-bit
kubectl -n logging rollout status daemonset/fluent-bit --timeout=300s
```

- If the app ever hits `ImagePullBackOff`, verify that:
  - CI has published `:stable`
  - or manually set the deployment image to a known full SHA from Artifact Registry

## 10. Teardown

Destroy infrastructure:

```bash
terraform -chdir=infra destroy -auto-approve
```

Validate cleanup:

```bash
gcloud container clusters list --project devops-486417
```

## 11. Reviewer Checklist

- Terraform provisions and destroys the cluster
- app deploys successfully
- CI builds/tests and pushes SHA-tagged image
- CD deploys exact SHA to the cluster
- Prometheus and Grafana are healthy
- alert rule is applied
- KEDA scales up and back down
- Fluent Bit, Elasticsearch, and Kibana are healthy
- `weather` namespace logs are visible in Kibana
