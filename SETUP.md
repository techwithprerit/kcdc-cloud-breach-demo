# One-time setup (before the talk, not on stage)

Two existing projects — **`my-insecure-project`** and **`my-secure-project`** — one small
Spot cluster each. Do this the day before, rehearse, then `make pause` (or
`make down`). Cost stays tiny; see `COST.md`.

## 0. Prerequisites
- `gcloud` (run `gcloud auth login` **and** `gcloud auth application-default login`)
- `terraform` ≥ 1.5, `kubectl`, `docker` (optional), `envsubst` (gettext), `cosign` ≥ v2, Python 3.11+
- You are `roles/owner` (or equivalent) on both projects; billing is linked.
- Swarm deps: `pip install -r swarm/requirements.txt` (add `anthropic` for LLM mode).

## 1. Provision both clusters (cheap)
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # then set YOUR two project IDs
terraform init && terraform apply              # or: make up   (from repo root)
cd ..
```
This creates, in each project: an Artifact Registry repo, a zonal GKE cluster with
a single Spot `e2-standard-2` node, and (secure only) Workload Identity + Secret
Manager secrets. It does **not** create the projects and leaves APIs enabled on
teardown.

## 2. Capture the environment
```bash
make env > .env                                # PROJECT_*, IMAGE_*, GSA_EMAIL, ...
. ./.env
```

## 3. Build the images (and record the signer)
```bash
make images    # insecure (fat, unsigned) + secure (SBOM->scan->sign->SLSA) + poison (both registries)
make signer    # auto-detects who signed the secure image -> writes CI_SIGNER_EMAIL to .env
. ./.env       # re-source so the new value is picked up
```
Notes:
- `make images-secure` **gates on CVEs** (trivy). Default blocks on CRITICAL and
  reports HIGH; flip `_SEVERITY=HIGH,CRITICAL` to demo the strict gate (triaged
  HIGHs are waived in `.trivyignore`). A genuine CRITICAL will stop the build —
  that's the gate working; bump the base in `app/Dockerfile.secure`.
- cosign keyless may open a browser once to establish the signing identity. Whoever
  you approve as becomes the signer; `make signer` captures it so the Kyverno policy
  matches automatically.

## 4. Credentials + deploy
```bash
make creds     # contexts named 'insecure' / 'secure'
make deploy    # both clusters; Kyverno signature enforcement on secure
```

## 5. Pre-flight + rehearse
```bash
make preflight # must print READY ✅
```
Run all of `RUNBOOK.md` once end to end.

## 6. Save money until showtime
```bash
make pause     # scale both node pools to 0    (make resume ~10 min before you present)
# or, when fully done:
make down      # delete both clusters (keeps images/secrets)
make nuke      # destroy everything this demo created
```

### Optional stronger foundation story
Set `enable_org_policies = true` and/or `enable_binauthz = true` in
`terraform.tfvars` if you hold the extra roles (`orgpolicy.policyAdmin`, Binary
Authorization admin). Left off by default so `apply` never fails on permissions;
Kyverno enforces image signatures either way.

### No GCP for rehearsal
`make fallback-up` runs the whole thing on minikube, zero cloud cost.
