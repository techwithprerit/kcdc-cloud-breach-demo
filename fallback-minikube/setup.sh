#!/usr/bin/env bash
# One-time setup for the OFFLINE minikube fallback. Run before the talk.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> starting minikube (Calico CNI so NetworkPolicy is actually enforced)"
minikube start --cni=calico --cpus=4 --memory=6g

echo "==> building the app image straight into minikube's docker"
minikube image build -t dealsvc:demo -f app/Dockerfile .

echo "==> (optional) install Kyverno to demo admission policies offline"
echo "    kubectl apply -f https://github.com/kyverno/kyverno/releases/download/v1.13.0/install.yaml"

echo "==> applying the INSECURE stack"
kubectl apply -f fallback-minikube/00-insecure.yaml
kubectl -n demo-insecure rollout status deploy/dealsvc --timeout=90s

cat <<'EOF'

Ready. Two terminals for the demo:

  # terminal A — expose the insecure app
  kubectl -n demo-insecure port-forward svc/dealsvc 8080:80

  # terminal B — attack it
  cd swarm
  python swarm.py --target http://127.0.0.1:8080 --label insecure \
    --metadata-url http://metadata.demo-insecure.svc.cluster.local/token
  #   (or from inside the cluster, metadata resolves as http://metadata/...)

Then bring up the secure stack and re-run:

  kubectl apply -f fallback-minikube/10-secure.yaml
  kubectl -n demo-secure rollout status deploy/dealsvc --timeout=90s
  kubectl -n demo-secure port-forward svc/dealsvc 8081:80
  python swarm.py --target http://127.0.0.1:8081 --label secure

Watch the pod take restarts under the flood:
  watch -n1 kubectl -n demo-insecure get pods
EOF
