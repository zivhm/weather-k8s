#!/usr/bin/env bash
set -euo pipefail

DESTROY_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destroy)
      DESTROY_MODE=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--destroy]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

read -rp "GCP Project ID [devops-486417]: " PROJECT_ID
PROJECT_ID="${PROJECT_ID:-devops-486417}"

read -rp "GKE Cluster Name [weather-cluster]: " CLUSTER_NAME
CLUSTER_NAME="${CLUSTER_NAME:-weather-cluster}"

read -rp "GKE Cluster Zone [us-central1-a]: " CLUSTER_ZONE
CLUSTER_ZONE="${CLUSTER_ZONE:-us-central1-a}"

REGION="${CLUSTER_ZONE%-*}"
REPOSITORY="weather"
IMAGE_NAME="weather-app"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}"
WINDY_WEBCAMS_API_KEY="${WINDY_WEBCAMS_API_KEY:-}"

if [[ "$DESTROY_MODE" == false && -t 0 && -z "$WINDY_WEBCAMS_API_KEY" ]]; then
  read -rsp "Windy Webcams API key (optional, press Enter to skip): " WINDY_WEBCAMS_API_KEY
  echo
fi

if git rev-parse --short HEAD >/dev/null 2>&1; then
  IMAGE_TAG="$(git rev-parse --short HEAD)"
else
  IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Fail early if a required local CLI tool is missing.
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

# Verify the local machine has every CLI the script depends on.
for cmd in terraform gcloud kubectl helm docker; do
  require_cmd "$cmd"
done

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
if [[ -z "$ACTIVE_ACCOUNT" ]]; then
  echo "No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

# Verify Application Default Credentials exist for Terraform and GCP API calls.
gcloud auth application-default print-access-token >/dev/null 2>&1 || {
  echo "ADC not found. Run: gcloud auth application-default login" >&2
  exit 1
}

TF_ARGS=(
  -var "project_id=$PROJECT_ID"
  -var "region=$REGION"
  -var "cluster_location=$CLUSTER_ZONE"
  -var "cluster_name=$CLUSTER_NAME"
)

echo "PROJECT_ID=$PROJECT_ID"
echo "CLUSTER_NAME=$CLUSTER_NAME"
echo "CLUSTER_ZONE=$CLUSTER_ZONE"
echo "REGION=$REGION"
echo "IMAGE_URI=$IMAGE_URI:$IMAGE_TAG"
echo

if [[ "$DESTROY_MODE" == true ]]; then
  # Initialize Terraform providers/modules before destroy so teardown can run reliably.
  terraform -chdir=infra init

  # Destroy the Terraform-managed infrastructure using the same runtime variables used on apply.
  terraform -chdir=infra destroy -auto-approve "${TF_ARGS[@]}"

  # List remaining clusters to confirm the target cluster was removed.
  gcloud container clusters list --project "$PROJECT_ID"
  exit 0
fi

# Initialize Terraform providers/modules before apply.
terraform -chdir=infra init

# Create or reconcile the VPC, subnet, GKE cluster, and node pool from the infra code.
terraform -chdir=infra apply -auto-approve "${TF_ARGS[@]}"

# Fetch kubeconfig credentials for the newly created cluster into the local kubectl context.
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --zone "$CLUSTER_ZONE" \
  --project "$PROJECT_ID"

# Confirm the cluster is reachable and nodes are registered.
kubectl get nodes

# Configure Docker to authenticate pushes to this region's Artifact Registry endpoint.
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build the weather app container image from the app source directory.
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" apps/weather

# Tag the local image with both an immutable tag and the stable bootstrap tag.
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_URI}:${IMAGE_TAG}"
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${IMAGE_URI}:stable"

# Push both image tags so Kubernetes can pull the exact build and the stable fallback tag.
docker push "${IMAGE_URI}:${IMAGE_TAG}"
docker push "${IMAGE_URI}:stable"

# Apply the weather namespace before any namespaced app resources.
kubectl apply -f deploy/k8s/namespace.yaml

# Create or update the runtime secret so optional camera support can be enabled without
# committing sensitive values into the repo.
kubectl -n weather create secret generic weather-secret \
  --from-literal=WINDY_WEBCAMS_API_KEY="$WINDY_WEBCAMS_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# Apply the app manifests through Kustomize so config and workload changes stay bundled.
kubectl apply -k deploy/k8s

# Override the deployment image to the exact image tag built in this script for traceable rollout.
kubectl -n weather set image deployment/weather-app weather-app="${IMAGE_URI}:${IMAGE_TAG}"

# Wait until the weather app deployment rollout completes successfully.
kubectl -n weather rollout status deployment/weather-app --timeout=300s

EXTERNAL_IP=""
for _ in {1..36}; do
  # Poll the LoadBalancer service until the cloud provider assigns an external IP.
  EXTERNAL_IP="$(kubectl -n weather get svc weather-service -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  [[ -n "$EXTERNAL_IP" ]] && break
  sleep 10
done

# Add the Helm repos needed for monitoring, autoscaling, and logging components.
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
helm repo add elastic https://helm.elastic.co >/dev/null 2>&1 || true
helm repo add fluent https://fluent.github.io/helm-charts >/dev/null 2>&1 || true

# Refresh Helm repository indexes before installing or upgrading charts.
helm repo update

# Ensure the monitoring namespace exists before installing the Prometheus/Grafana stack.
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

# Install or upgrade kube-prometheus-stack and wait until the chart resources are ready.
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --wait \
  --timeout 10m

# Apply the custom Prometheus alert rules for the weather app.
kubectl apply -f deploy/monitoring/weather-alerts.yaml
kubectl apply -f deploy/monitoring/grafana-dashboard-weather-app.yaml

# Ensure the KEDA namespace exists before installing the autoscaling operator.
kubectl create namespace keda --dry-run=client -o yaml | kubectl apply -f -

# Install or upgrade KEDA and wait until the operator is ready.
helm upgrade --install keda kedacore/keda \
  -n keda \
  --wait \
  --timeout 10m

# Apply the weather app ScaledObject so KEDA can create and manage the HPA.
kubectl apply -f deploy/keda/scaledobject.yaml

# Create the logging namespace used by Elasticsearch, Kibana, and Fluent Bit.
kubectl apply -f deploy/logging/namespace.yaml

# Install or upgrade Elasticsearch and wait for the single-node stateful workload to become ready.
helm upgrade --install weather-logs elastic/elasticsearch \
  -n logging \
  -f deploy/logging/elasticsearch-values.yaml \
  --wait \
  --timeout 15m

# Install or upgrade Kibana and wait for the UI deployment to become ready.
helm upgrade --install kibana elastic/kibana \
  -n logging \
  -f deploy/logging/kibana-values.yaml \
  --wait \
  --timeout 15m

# Install or upgrade Fluent Bit and wait for the log forwarder daemonset to become ready.
helm upgrade --install fluent-bit fluent/fluent-bit \
  -n logging \
  -f deploy/logging/fluent-bit-values.yaml \
  --wait \
  --timeout 15m

# Read the generated Elasticsearch password used to log into Kibana.
KIBANA_PASSWORD="$(kubectl -n logging get secret weather-logs-master-credentials -o jsonpath='{.data.password}' | base64 -d)"

echo
echo "Done"
echo "Image: ${IMAGE_URI}:${IMAGE_TAG}"
echo "Service IP: ${EXTERNAL_IP:-pending}"
echo "City cameras: $([[ -n "$WINDY_WEBCAMS_API_KEY" ]] && echo enabled || echo disabled)"
echo "Kibana user: elastic"
echo "Kibana password: ${KIBANA_PASSWORD}"
echo "Checks:"
echo "  kubectl -n weather get svc weather-service"
echo "  kubectl -n monitoring get pods"
echo "  kubectl -n weather get scaledobject,hpa"
echo "  kubectl -n logging get pods"
echo "  kubectl -n logging port-forward svc/kibana-kibana 5601:5601"

if [[ -n "$EXTERNAL_IP" ]] && command -v curl >/dev/null 2>&1; then
  echo
  echo "Health:"
  # Call the public health endpoint as a final quick smoke test of the deployed app.
  curl -fsS "http://${EXTERNAL_IP}/healthz" || true
  echo
fi
