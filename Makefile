# cloud-breach-demo — two existing GCP projects (my-insecure-project / my-secure-project),
# cost-optimized: one small zonal Spot cluster per project, no LoadBalancer.
# Config from .env  (create it: `make env > .env`, then append CI_SIGNER_EMAIL).
-include .env
export

PROJECT_INSECURE ?= my-insecure-project
PROJECT_SECURE   ?= my-secure-project
REGION           ?= us-central1
ZONE             ?= us-central1-a
NODE_MAX         ?= 2
PYTHON           ?= python3
AGENTS           ?= 12
DURATION         ?= 8
SWARM             = $(PYTHON) swarm/swarm.py
META_URL          = http://metadata.dealsvc.svc.cluster.local/token

.PHONY: help
help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'
	@echo "  \033[33mcost:\033[0m 2x Spot e2-standard-2 (one per project), no LB. 'make pause' between rehearsals, 'make down' when done."

# ============================ SETUP (one-time) =============================
setup: up images creds deploy ## Full cheap setup for BOTH projects
	@echo "\n✅ demo ready. Cost is running — 'make pause' between rehearsals, 'make down' when finished."

up: ## Create both cost-optimized clusters + Artifact Registry + WI + secrets
	cd terraform && terraform init -input=false && terraform apply -auto-approve
	@$(MAKE) --no-print-directory cost

env: ## Print .env exports (run: make env > .env, then add CI_SIGNER_EMAIL)
	@cd terraform && terraform output -raw env_exports

images: images-insecure images-secure image-poison ## Build all images
images-insecure:
	gcloud builds submit --project $(PROJECT_INSECURE) --config supplychain/cloudbuild-insecure.yaml \
	  --substitutions=_REGION=$(REGION),_REPO=demo,_IMAGE=dealsvc,_TAG=insecure .
images-secure: ## build -> SBOM -> scan(gate) -> sign -> SLSA attest (secure project)
	gcloud builds submit --project $(PROJECT_SECURE) --config supplychain/cloudbuild-secure.yaml \
	  --substitutions=_REGION=$(REGION),_REPO=demo,_IMAGE=dealsvc,_TAG=secure .
image-poison: ## unsigned poison image, pushed to BOTH registries (so it's always pullable)
	gcloud builds submit --project $(PROJECT_INSECURE) --config supplychain/cloudbuild-poison.yaml \
	  --substitutions=_REGION=$(REGION),_REPO=demo,_IMAGE=dealsvc,_TAG=poison .
	gcloud builds submit --project $(PROJECT_SECURE) --config supplychain/cloudbuild-poison.yaml \
	  --substitutions=_REGION=$(REGION),_REPO=demo,_IMAGE=dealsvc,_TAG=poison .

creds: ## Fetch credentials; name the contexts 'insecure' / 'secure'
	gcloud container clusters get-credentials insecure --project $(PROJECT_INSECURE) --zone $(ZONE)
	-kubectl config delete-context insecure 2>/dev/null
	kubectl config rename-context gke_$(PROJECT_INSECURE)_$(ZONE)_insecure insecure
	gcloud container clusters get-credentials secure --project $(PROJECT_SECURE) --zone $(ZONE)
	-kubectl config delete-context secure 2>/dev/null
	kubectl config rename-context gke_$(PROJECT_SECURE)_$(ZONE)_secure secure

signer: ## Auto-detect who signed the secure image -> writes CI_SIGNER_EMAIL to .env
	@S=$$(cosign verify $(IMAGE_SECURE) --certificate-oidc-issuer https://accounts.google.com --certificate-identity-regexp '.+' -o json 2>/dev/null | $(PYTHON) -c 'import sys,json; print(json.load(sys.stdin)[0]["optional"]["Subject"])' 2>/dev/null); \
	 if [ -n "$$S" ]; then \
	   if grep -q "^export CI_SIGNER_EMAIL=" .env 2>/dev/null; then sed -i.bak "s|^export CI_SIGNER_EMAIL=.*|export CI_SIGNER_EMAIL=$$S|" .env; else echo "export CI_SIGNER_EMAIL=$$S" >> .env; fi; \
	   echo "signer identity = $$S  (written to .env — re-source it: . ./.env)"; \
	 else echo "could not detect signer — is $(IMAGE_SECURE) built + signed yet?"; fi

deploy: ## Deploy to both clusters (+ Kyverno signature enforcement on secure)
	# --- insecure cluster ---
	envsubst < k8s/insecure/deployment.yaml | kubectl --context insecure apply -f -
	kubectl --context insecure apply -f k8s/insecure/rbac.yaml
	kubectl --context insecure -n dealsvc rollout status deploy/dealsvc --timeout=120s
	# --- secure cluster: Kyverno first, then the workload ---
	# server-side apply: Kyverno's CRDs exceed the 256KB client-side annotation limit
	kubectl --context secure apply --server-side --force-conflicts -f https://github.com/kyverno/kyverno/releases/download/v1.13.0/install.yaml
	kubectl --context secure -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s
	# Give Kyverno a GCP identity (Workload Identity) so it can pull from AR to verify signatures
	kubectl --context secure -n kyverno annotate sa kyverno-admission-controller iam.gke.io/gcp-service-account=$(GSA_EMAIL) --overwrite
	kubectl --context secure -n kyverno rollout restart deploy/kyverno-admission-controller
	kubectl --context secure -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s
	envsubst < k8s/policies/kyverno-policies.yaml | kubectl --context secure apply -f -
	envsubst < k8s/secure/deployment.yaml | kubectl --context secure apply -f -
	kubectl --context secure apply -f k8s/secure/networkpolicy.yaml
	kubectl --context secure -n dealsvc rollout status deploy/dealsvc --timeout=120s

# ============================== LIVE DEMO ==================================
posture: ## Foundation + runtime posture diff (both projects)
	bash scripts/posture.sh

attack-insecure: ## Swarm vs the insecure cluster (auto port-forward :8080)
	@kubectl --context insecure -n dealsvc port-forward svc/dealsvc 8080:80 >/dev/null 2>&1 & echo $$! >/tmp/pf-ins.pid; sleep 4; \
	 $(SWARM) --target http://127.0.0.1:8080 --label insecure --agents $(AGENTS) --duration $(DURATION) --metadata-url $(META_URL); \
	 kill `cat /tmp/pf-ins.pid` 2>/dev/null

attack-secure: ## Same swarm vs the secure cluster (auto port-forward :8081)
	@kubectl --context secure -n dealsvc port-forward svc/dealsvc 8081:80 >/dev/null 2>&1 & echo $$! >/tmp/pf-sec.pid; sleep 4; \
	 $(SWARM) --target http://127.0.0.1:8081 --label secure --agents $(AGENTS) --duration $(DURATION); \
	 kill `cat /tmp/pf-sec.pid` 2>/dev/null

supplychain: ## Verify signed vs poison; poison RUNS on insecure, BLOCKED on secure
	@echo "### SIGNED image:"; CI_SIGNER_EMAIL=$(CI_SIGNER_EMAIL) bash supplychain/verify.sh $(IMAGE_SECURE) || true
	@echo "### POISON image:"; CI_SIGNER_EMAIL=$(CI_SIGNER_EMAIL) bash supplychain/verify.sh $(IMAGE_POISON) || true
	@echo "### poison -> INSECURE cluster (expect: runs):"; \
	  IMAGE_POISON=$(IMAGE_POISON) envsubst < k8s/poison/poison-deploy.yaml | kubectl --context insecure apply -f - || true
	@echo "### poison -> SECURE cluster (expect: BLOCKED by Kyverno signature check):"; \
	  IMAGE_POISON=$(IMAGE_POISON_SECURE) envsubst < k8s/poison/poison-deploy.yaml | kubectl --context secure apply -f - || true

watch: ## Watch pods on both clusters (insecure restarts under the flood)
	watch -n1 'echo INSECURE:; kubectl --context insecure -n dealsvc get pods; echo; echo SECURE:; kubectl --context secure -n dealsvc get pods'

preflight: ## Readiness check
	bash scripts/preflight.sh

# ============================ COST CONTROLS ================================
cost: ## Show cost knobs + teardown reminder
	@echo "----------------------------------------------------------------"
	@echo " COST: 2x Spot e2-standard-2 (one per project), zonal clusters, NO LoadBalancer."
	@echo "   pause  -> scale BOTH node pools to 0 (near-zero cost, keeps everything)"
	@echo "   resume -> scale BOTH back to 1 node"
	@echo "   down   -> delete BOTH clusters (keeps registries/secrets)"
	@echo "   nuke   -> terraform destroy EVERYTHING this demo created"
	@echo " Note: GKE free tier covers ONE zonal cluster's mgmt fee per billing account;"
	@echo "       the 2nd cluster's control plane is ~\$$0.10/hr while it exists."
	@echo "----------------------------------------------------------------"

pause: ## Scale BOTH node pools to 0
	for pair in "$(PROJECT_INSECURE) insecure" "$(PROJECT_SECURE) secure"; do set -- $$pair; \
	  gcloud container node-pools update spot-pool --cluster $$2 --zone $(ZONE) --project $$1 --enable-autoscaling --min-nodes=0 --max-nodes=$(NODE_MAX) -q; \
	  gcloud container clusters resize $$2 --node-pool spot-pool --zone $(ZONE) --project $$1 --num-nodes=0 -q; done
	@echo "paused both clusters — 'make resume' before the talk."

resume: ## Scale BOTH node pools back to 1
	for pair in "$(PROJECT_INSECURE) insecure" "$(PROJECT_SECURE) secure"; do set -- $$pair; \
	  gcloud container node-pools update spot-pool --cluster $$2 --zone $(ZONE) --project $$1 --enable-autoscaling --min-nodes=1 --max-nodes=$(NODE_MAX) -q; \
	  gcloud container clusters resize $$2 --node-pool spot-pool --zone $(ZONE) --project $$1 --num-nodes=1 -q; done

down: ## Delete BOTH clusters + node pools only (keeps registries + secrets)
	cd terraform && terraform destroy -auto-approve \
	  -target=google_container_node_pool.np -target=google_container_cluster.c
	@echo "clusters deleted. 'make up && make creds && make deploy' to rebuild fast."

nuke: ## terraform destroy EVERYTHING this demo created
	cd terraform && terraform destroy -auto-approve

# =================== LOCAL DEMO (free, offline, no GCP) ====================
# The seamless way to try the repo: runtime attack/defense + SSRF on minikube.
local-up: ## [FREE] minikube: build image, deploy insecure + secure namespaces
	bash fallback-minikube/setup.sh
	kubectl --context minikube apply -f fallback-minikube/10-secure.yaml
	kubectl --context minikube -n demo-secure rollout status deploy/dealsvc --timeout=150s
	@echo "\n✅ local demo ready. Try:  make local-attack-insecure   then   make local-attack-secure"

local-attack-insecure: ## [FREE] swarm vs the local INSECURE app (auto port-forward :8080)
	@kubectl --context minikube -n demo-insecure port-forward svc/dealsvc 8080:80 >/dev/null 2>&1 & echo $$! >/tmp/pf-li.pid; sleep 4; \
	 $(SWARM) --target http://127.0.0.1:8080 --label insecure --agents $(AGENTS) --duration $(DURATION) \
	   --metadata-url http://metadata.demo-insecure.svc.cluster.local/token; \
	 kill `cat /tmp/pf-li.pid` 2>/dev/null

local-attack-secure: ## [FREE] swarm vs the local SECURE app (auto port-forward :8081)
	@kubectl --context minikube -n demo-secure port-forward svc/dealsvc 8081:80 >/dev/null 2>&1 & echo $$! >/tmp/pf-ls.pid; sleep 4; \
	 $(SWARM) --target http://127.0.0.1:8081 --label secure --agents $(AGENTS) --duration $(DURATION); \
	 kill `cat /tmp/pf-ls.pid` 2>/dev/null

local-watch: ## [FREE] watch local pods (insecure restarts under the flood)
	watch -n1 'echo INSECURE:; kubectl --context minikube -n demo-insecure get pods; echo; echo SECURE:; kubectl --context minikube -n demo-secure get pods'

local-down: ## [FREE] tear down the local minikube demo
	minikube delete
