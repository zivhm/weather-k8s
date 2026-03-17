# Weather App on Kubernetes

This repo delivers the task end to end:

- Terraform provisions GKE, networking, and a node pool
- Terraform also creates the Artifact Registry repository used by CI/CD
- Flask weather app runs on Kubernetes
- GitHub Actions CI builds/tests and pushes SHA-tagged images
- GitHub Actions CD deploys the exact SHA
- Prometheus/Grafana provide monitoring
- KEDA provides autoscaling
- Fluent Bit, Elasticsearch, and Kibana provide centralized logging

## Repo Layout

- `infra/`: Terraform
- `apps/weather/`: app code and Dockerfile
- `deploy/k8s/`: app manifests
- `deploy/monitoring/`: alert rule
- `deploy/keda/`: autoscaling
- `deploy/logging/`: logging values
- `.github/workflows/`: CI/CD

## Prerequisites

- Terraform
- gcloud
- kubectl
- helm
- Docker
- GCP project with billing enabled

Authenticate:

```bash
gcloud auth login
gcloud auth application-default login
```

GitHub secrets:

- `GCP_PROJECT_ID`
- `GCP_SA_KEY`
- `WINDY_WEBCAMS_API_KEY` (optional, for live city cameras in CD deployments)

Local development:

- Create `apps/weather/.env` from `apps/weather/.env.example`
- Put `WINDY_WEBCAMS_API_KEY` in that file for local camera testing
- `.env` is ignored by git and excluded from Docker builds

## Quickstart

### Deploy using script:

```bash
./setup.sh

# then follow the instructions in the script output

```

`setup.sh` will prompt for an optional `WINDY_WEBCAMS_API_KEY`, or you can export it first and let the script reuse that value.

### Deploy manually:

### 1. Create the cluster

```bash
terraform -chdir=infra init
terraform -chdir=infra apply
gcloud container clusters get-credentials weather-cluster --zone us-central1-a --project devops-486417
kubectl get nodes
```

### 2. Deploy the app

Apply the namespace first, create the runtime secret, then apply the Kustomize bundle:

```bash
export WINDY_WEBCAMS_API_KEY="" # optional

kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n weather create secret generic weather-secret \
  --from-literal=WINDY_WEBCAMS_API_KEY="$WINDY_WEBCAMS_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k deploy/k8s
kubectl -n weather rollout status deployment/weather-app
kubectl -n weather get svc weather-service
```

The deployment uses:

```text
us-central1-docker.pkg.dev/devops-486417/weather/weather-app:stable
```

Test:

```text
http://<EXTERNAL-IP>/healthz
http://<EXTERNAL-IP>/weather?city=Berlin
http://<EXTERNAL-IP>/city-camera?city=Berlin
```

Optional live camera support:

- Set `WINDY_WEBCAMS_API_KEY` to enable public city camera lookup through Windy Webcams
- CD recreates `weather-secret` from the GitHub Actions secret each time it deploys
- Camera availability depends on a public webcam existing near the selected city
- Default weather/geocoding timeout is `12` seconds; camera lookups use a shorter `6` second timeout

### 3. Install monitoring

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring
kubectl apply -f deploy/monitoring/weather-alerts.yaml
kubectl apply -f deploy/monitoring/grafana-dashboard-weather-app.yaml
```

Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d && echo
```

The stack auto-loads the `Weather App Overview` dashboard from `deploy/monitoring/grafana-dashboard-weather-app.yaml`.

### 4. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
kubectl create namespace keda --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install keda kedacore/keda -n keda
kubectl apply -f deploy/keda/scaledobject.yaml
kubectl -n weather get scaledobject,hpa
```

Scale test:

```bash
kubectl -n weather run loadgen --rm -it --restart=Never --image=busybox:1.36 --command -- sh -c 'for i in $(seq 1 50); do while true; do wget -q -O- http://weather-service.weather.svc.cluster.local/weather?city=Berlin >/dev/null; done & done; wait'
```

### 5. Install logging

```bash
helm repo add elastic https://helm.elastic.co
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
kubectl apply -f deploy/logging/namespace.yaml
helm upgrade --install weather-logs elastic/elasticsearch -n logging -f deploy/logging/elasticsearch-values.yaml
kubectl -n logging rollout status statefulset/weather-logs-master --timeout=600s
helm upgrade --install kibana elastic/kibana -n logging -f deploy/logging/kibana-values.yaml
helm upgrade --install fluent-bit fluent/fluent-bit -n logging -f deploy/logging/fluent-bit-values.yaml
```

Kibana:

```bash
kubectl -n logging port-forward svc/kibana-kibana 5601:5601
kubectl -n logging get secret weather-logs-master-credentials -o jsonpath="{.data.password}" | base64 -d && echo
```

In Discover, use data view `weather-*` and filter:

```text
kubernetes.namespace_name : "weather"
```

## CI/CD

- CI: `.github/workflows/ci.yaml`
  - tests the app
  - builds the image
  - pushes `weather-app:<commit-sha>` and `weather-app:stable` on `main`
- CD: `.github/workflows/cd.yaml`
  - runs after successful CI
  - recreates `weather-secret` from GitHub secrets
  - reapplies the Kustomize app bundle
  - deploys the exact commit SHA image

## Destroy

```bash
./setup.sh --destroy

# or destroy manually:
terraform -chdir=infra destroy -auto-approve
gcloud container clusters list --project devops-486417
terraform -chdir=infra state list
```

Expected:

- no cluster in GCP
- empty Terraform state
