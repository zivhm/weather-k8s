# Weather App on Kubernetes

Production-like weather platform on GKE with Terraform-managed infrastructure, GitHub Actions CI/CD, Prometheus/Grafana monitoring, KEDA autoscaling, and centralized logging with Fluent Bit, Elasticsearch, and Kibana.

## Task Fit

This repo covers the assignment requirements:

- Terraform provisions networking, a GKE cluster, and a managed node pool.
- A Flask weather app is containerized and deployed to Kubernetes.
- GitHub Actions CI tests, builds, and pushes commit-SHA plus `stable` image tags.
- GitHub Actions CD deploys the exact commit SHA to the cluster.
- Prometheus and Grafana provide monitoring plus a custom alert rule.
- KEDA autoscaling is configured and testable.
- Fluent Bit, Elasticsearch, and Kibana provide centralized logging.
- Teardown is documented and reproducible.

## Repo Layout

- `infra/`: Terraform for VPC, subnet, GKE cluster, and node pool
- `apps/weather/`: Flask app, tests, requirements, and Dockerfile
- `deploy/k8s/`: namespace, config, secret, service, and deployment manifests
- `deploy/monitoring/`: Prometheus alert rules
- `deploy/keda/`: KEDA `ScaledObject`
- `deploy/logging/`: Helm values for Elasticsearch, Kibana, and Fluent Bit
- `.github/workflows/`: CI and CD pipelines
- `docs/`: architecture assets

## Prerequisites

- Terraform `>= 1.5`
- `gcloud`
- `kubectl`
- `helm`
- Docker
- Python `3.12+`
- A GCP project with billing enabled

Authenticate locally:

```bash
gcloud auth login
gcloud auth application-default login
```

GitHub Actions secrets:

- `GCP_PROJECT_ID`
- `GCP_SA_KEY`

The CI/CD service account needs at least:

- Artifact Registry writer access
- GKE deploy access

## Quickstart

This is the fastest reviewer path from empty project to working platform.

### 1. Provision infrastructure

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

### 2. Deploy the app

Apply the namespace first, then the namespaced resources:

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl -n weather rollout status deployment/weather-app
```

The deployment bootstraps from:

```text
us-central1-docker.pkg.dev/devops-486417/weather/weather-app:stable
```

Get the external IP:

```bash
kubectl -n weather get svc weather-service
```

Then open:

```text
http://<EXTERNAL-IP>/healthz
http://<EXTERNAL-IP>/weather?city=Berlin
```

### 3. Install monitoring

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring
kubectl apply -f deploy/monitoring/weather-alerts.yaml
kubectl -n monitoring get pods
```

### 4. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
kubectl create namespace keda --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install keda kedacore/keda -n keda
kubectl apply -f deploy/keda/scaledobject.yaml
kubectl -n weather get scaledobject,hpa
```

### 5. Install logging

Install in this order:

```bash
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
kubectl apply -f deploy/logging/namespace.yaml
helm upgrade --install weather-logs elastic/elasticsearch -n logging -f deploy/logging/elasticsearch-values.yaml
kubectl -n logging rollout status statefulset/weather-logs-master --timeout=600s
helm upgrade --install kibana elastic/kibana -n logging -f deploy/logging/kibana-values.yaml
helm upgrade --install fluent-bit fluent/fluent-bit -n logging -f deploy/logging/fluent-bit-values.yaml
kubectl -n logging get pods
```

## CI/CD

### CI

File: `.github/workflows/ci.yaml`

- Runs on pull requests and pushes to `main`
- Installs Python dependencies
- Syntax-checks `app.py`
- Runs `pytest`
- Builds the container image
- On `main`, pushes:
  - `weather-app:<commit-sha>`
  - `weather-app:stable`

### CD

File: `.github/workflows/cd.yaml`

- Triggered by successful CI via `workflow_run`
- Checks out the exact tested commit
- Applies Kubernetes manifests
- Sets the deployment image to the exact commit SHA
- Waits for rollout and verifies the deployed image

This keeps deployments traceable to a specific build instead of a mutable tag.

## Validation

### App

```bash
kubectl -n weather rollout status deployment/weather-app
kubectl -n weather get svc weather-service
```

Expected:

- pods become `Running`
- the `LoadBalancer` service gets an external IP
- `/healthz` and `/weather` respond successfully

### Monitoring

Port-forward Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Open:

```text
http://localhost:3000
```

Get the admin password:

```bash
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d && echo
```

Alert rule:

- `WeatherAppNoRunningPods` in `deploy/monitoring/weather-alerts.yaml`

### Autoscaling

Current config:

- CPU trigger
- threshold: `10%`
- min replicas: `1`
- max replicas: `5`

Watch pods:

```bash
kubectl -n weather get pods -w
```

Watch HPA:

```bash
kubectl -n weather get hpa -w
```

Generate load:

```bash
kubectl -n weather run loadgen --rm -it --restart=Never --image=busybox:1.36 --command -- sh -c 'for i in $(seq 1 50); do while true; do wget -q -O- http://weather-service.weather.svc.cluster.local/weather?city=Berlin >/dev/null; done & done; wait'
```

Expected:

- HPA target exceeds threshold
- replicas scale up
- replicas scale back down after load stops

### Logging

Check Fluent Bit:

```bash
kubectl -n logging logs -l app.kubernetes.io/name=fluent-bit --tail=100
```

You should not see repeated `_bulk` `401` errors.

Access Kibana:

```bash
kubectl -n logging port-forward svc/kibana-kibana 5601:5601
```

Open:

```text
http://localhost:5601
```

Get the Elasticsearch password:

PowerShell:

```powershell
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String((kubectl -n logging get secret weather-logs-master-credentials -o jsonpath='{.data.password}')))
```

Bash:

```bash
kubectl -n logging get secret weather-logs-master-credentials -o jsonpath="{.data.password}" | base64 -d && echo
```

In Kibana Discover:

- create or select data view `weather-*`
- search `kubernetes.namespace_name : "weather"`

Fresh requests to `/weather` should appear in Discover.

## Local Development

Run tests:

```bash
pytest -q apps/weather/tests
```

Run the app locally:

```bash
python apps/weather/app.py
```

Open:

```text
http://localhost:8080/healthz
http://localhost:8080/weather?city=Berlin
```

## Operational Notes

- Logging is the most resource-sensitive part of the stack.
- Elasticsearch instability will usually break Kibana readiness too.
- If fresh logs stop appearing but older logs exist, restart Fluent Bit:

```bash
kubectl -n logging rollout restart daemonset/fluent-bit
kubectl -n logging rollout status daemonset/fluent-bit --timeout=300s
```

- If the app hits `ImagePullBackOff`, verify that CI has published `:stable` or update the deployment to a known SHA tag from Artifact Registry.

## Destroy

Tear everything down with Terraform:

```bash
terraform -chdir=infra destroy -auto-approve
```

Quick cleanup checks:

```bash
gcloud container clusters list --project devops-486417
terraform -chdir=infra state list
```

Expected:

- no cluster returned by `gcloud`
- empty Terraform state

Seeing only the GCP `default` network is normal.

## Reviewer Checklist

- Terraform provisions and destroys the cluster cleanly
- the app deploys and becomes reachable
- CI tests, builds, and pushes SHA-tagged images
- CD deploys the exact SHA image
- Prometheus and Grafana are healthy
- the custom alert rule is applied
- KEDA scales up and back down
- Fluent Bit, Elasticsearch, and Kibana are healthy
- logs from the `weather` namespace are visible in Kibana
