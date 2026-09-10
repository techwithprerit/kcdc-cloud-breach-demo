# Full walkthrough — deliver the cloud-breach demo end to end

This is the single doc that ties everything together: what the demo is, what's in
the repo, how the code works, exactly what to run, how to present it live, what it
costs, and how to recover when something misbehaves.

- **Quick refs:** `RUNBOOK.md` (stage script), `SETUP.md` (provisioning), `COST.md`
  (money), `ARCHITECTURE.md` (the vuln→fix map + diagram).

---

## 1. The idea in one paragraph
One app (`dealsvc`) runs in **two GCP projects** — `my-insecure-project` and
`my-secure-project`. The code is identical; only the **architecture** differs, across
three layers: **foundation** (IAM, VPC, org policy, Binary Authorization),
**supply chain** (image build, SBOM, scan, signing, SLSA provenance), and
**runtime** (Kubernetes identity, network, limits, admission). A swarm of
LLM-driven attacker agents runs the *same* attack against both. Insecure falls in
under a minute; secure deflects every objective. The scoreboard flips **red →
green** live. Thesis: breaches come from insecure defaults and over-trusting
architecture, not "bad code."

## 2. What you need to deliver it
- Two GCP projects you own (`my-insecure-project`, `my-secure-project`) with billing linked.
- Local tools: `gcloud`, `terraform`, `kubectl`, `envsubst`, `cosign` v2, Python 3.11+.
  (`helm` only if you switch secrets to the CSI driver — not needed by default.)
- ~20 min the day before to provision + rehearse. Cost: a few dollars, then tear down.
- Optional: `ANTHROPIC_API_KEY` to make the swarm genuinely LLM-planned (it falls
  back to a deterministic playbook without one — the demo never depends on a key).
- A laptop with the repo, and (recommended) minikube installed as an offline
  backup (`make fallback-up`).

## 3. Repo tour
```
cloud-breach-demo/
├─ app/                     the workload
│  ├─ main.py               FastAPI "deals" API; behavior toggled by env flags
│  ├─ Dockerfile            INSECURE image: fat base, root, unsigned
│  ├─ Dockerfile.secure     SECURE image: distroless, non-root -> clean SBOM
│  └─ requirements.txt
├─ swarm/                   the agentic attacker
│  ├─ swarm.py              orchestrator: recon, objectives, coordinated flood, scoreboard
│  ├─ llm.py                LLM "commander" (Anthropic/OpenAI) + offline fallback
│  ├─ playbook.py           objective catalog + deterministic plan + recon wordlist
│  └─ report.py             rich scoreboard + breach report
├─ terraform/               FOUNDATION: two existing projects, cheap clusters
│  ├─ projects.tf           APIs + Artifact Registry (both projects, for_each)
│  ├─ gke.tf                one Spot zonal cluster each; secure gets WI/DataplaneV2/etc.
│  ├─ security.tf           secure-only: WI GSA, Secret Manager, optional BinAuthz/org-policy
│  ├─ variables.tf outputs.tf versions.tf terraform.tfvars.example
├─ supplychain/             SUPPLY CHAIN: build/sign/verify
│  ├─ cloudbuild-insecure.yaml   build + push (no SBOM/scan/sign)
│  ├─ cloudbuild-secure.yaml     build -> SBOM(syft) -> scan(trivy gate) -> sign(cosign) -> SLSA attest
│  ├─ cloudbuild-poison.yaml     build the tampered image
│  ├─ poison/Dockerfile          the "backdoored" image (benign; adds /pwned)
│  └─ verify.sh                  cosign verify + verify-attestation (the live "prove it")
├─ k8s/                     RUNTIME: manifests per cluster
│  ├─ insecure/             root, no limits, mounted SA token, broad RBAC, fake metadata svc
│  ├─ secure/               non-root RO-fs, limits+HPA+PDB, WI SA, default-deny NetworkPolicy
│  ├─ policies/             Kyverno verifyImages (secure cluster; blocks unsigned images)
│  └─ poison/               the poison Deployment (applied to each cluster)
├─ fallback-minikube/       fully offline version of the whole story (no cloud cost)
├─ scripts/                 posture.sh (diff), preflight.sh (readiness), smoke.py (local test)
├─ Makefile                 every action is a short verb (see `make help`)
├─ RUNBOOK.md SETUP.md COST.md ARCHITECTURE.md WALKTHROUGH.md
└─ *.svg / *.excalidraw     the architecture diagram (import into slides)
```

## 4. How the code works

### 4a. The app (`app/main.py`)
A tiny FastAPI service. **The same image is used insecure and secure** — behavior
is switched by environment variables, which is the entire point (config, not code):

| Env flag (secure value) | Insecure default | Effect when set |
|---|---|---|
| `SECURE_DEBUG=1` | `/debug/env` dumps all env (secrets!) | endpoint returns 404 |
| `SECURE_SSRF=1` | `/fetch?url=` fetches anything | blocks link-local/metadata |
| `SECURE_ADMIN=1` | `/admin/*` open | requires `Authorization: Bearer $ADMIN_TOKEN` |
| `SECURE_RATELIMIT=1` | none | token-bucket → 429 under flood |
| `EXPENSIVE_OFFLOAD=1` | CPU work blocks the event loop | work offloaded, stays responsive |
| `BACKDOOR=1` (poison only) | — | exposes `/pwned` (proves code exec from a tampered image) |

Endpoints of note: `/deals` (business impact — discount is attacker-settable via
`/admin/config`), `/deals/search` (the CPU-heavy path used for the DoS),
`/debug/env` (secret leak), `/fetch` (SSRF), `/admin/secrets` (returns the mounted
k8s SA token → lateral movement).

### 4b. The swarm (`swarm/`) — why it's "agentic"
`swarm.py` runs an async pipeline:
1. **Recon** the target live.
2. **`llm.py` commander** turns recon into an ordered attack plan + a one-line
   "intent" in the operator's voice (Anthropic or OpenAI). No key → deterministic
   playbook from `playbook.py`, so a bad network can never break the demo.
3. **Worker agents** execute objectives; a subset runs a coordinated flood while a
   probe measures whether the service stays up (429 = defended; 5xx/timeout /
   failing health = broken).
4. **`report.py`** renders the live scoreboard + final breach report.

Safety: it **refuses** any target that isn't localhost / private / `*.svc` unless
you pass `--allow <host>` and `SWARM_I_OWN_THIS=1`. The "exploits" are just hitting
misconfigured endpoints on the app this repo ships + flooding it — no CVE weaponry,
no malware; `/pwned` only returns a marker.

### 4c. The infrastructure
- **Terraform** (`terraform/`) adds resources to the two existing projects: APIs,
  Artifact Registry, one Spot zonal GKE cluster each. The secure project's cluster
  gets Workload Identity, Dataplane V2 (so NetworkPolicy is enforced), GKE metadata
  concealment, shielded nodes, plus a least-priv GSA and Secret Manager secrets.
  Cheap by default (Spot, small disk, no LB); see `COST.md`.
- **Supply chain** (`supplychain/`) is two Cloud Build pipelines: the insecure one
  just builds+pushes; the secure one generates an SBOM (syft), **gates on
  HIGH/CRITICAL CVEs** (trivy), signs the image (cosign keyless → Fulcio+Rekor),
  and attaches SBOM + SLSA provenance attestations. `verify.sh` proves all three.
- **Runtime** (`k8s/`) is the two-namespace-free, two-cluster split: insecure
  cluster runs the permissive manifests; secure cluster enforces PSA `restricted`,
  default-deny NetworkPolicy, non-root read-only pods with limits + HPA, and
  **Kyverno** rejects any image not cosign-signed by your CI identity.

## 5. Step-by-step: from zero to ready
```bash
# 0) auth
gcloud auth login && gcloud auth application-default login

# 1) provision both cheap clusters
cd terraform && cp terraform.tfvars.example terraform.tfvars && terraform init && terraform apply
cd ..                                  # (or just: make up)

# 2) environment
make env > .env
PN=$(gcloud projects describe my-secure-project --format='value(projectNumber)')
echo "export CI_SIGNER_EMAIL=${PN}@cloudbuild.gserviceaccount.com" >> .env
. ./.env

# 3) images (insecure fat + secure signed + poison in both registries)
make images

# 4) credentials + deploy
make creds
make deploy

# 5) verify readiness, then rehearse the RUNBOOK
make preflight        # -> READY ✅
```
Between rehearsals: `make pause`. Before the talk: `make resume` then `make preflight`.

## 6. Delivering it live (15 min)
Follow `RUNBOOK.md`. The five acts, each a `make` verb:
1. `make posture` — two worlds, side by side.
2. `make attack-insecure` — swarm breaches everything.
3. `make supplychain` — signed vs poison; poison **runs** on insecure, **blocked** on secure.
4. `make attack-secure` — same swarm, all objectives held.
5. Architecture slide (`ARCHITECTURE.md` / the diagram) — map each vuln to its fix.

Presenter tips: keep `make watch` open on a second pane (pods restarting is a great
visual); pre-`resume` the clusters and run `make preflight` before you walk up; if
the venue Wi-Fi is shaky, the swarm is fine (offline commander), but if GCP itself
is unreachable, switch to `make fallback-up`.

## 7. Cost & teardown
See `COST.md`. Short version: Spot nodes + no LB + zonal clusters keep it to a few
dollars; `make pause` between runs, `make down` (keeps images) or `make nuke`
(everything) when finished. The day-of pattern: `resume` → present → `down`.

## 8. Troubleshooting
| Symptom | Fix |
|---|---|
| `make preflight` shows ✗ but doesn't crash | expected before setup — work the printed list top-to-bottom |
| `terraform apply` fails on org policy / BinAuthz IAM | leave `enable_org_policies`/`enable_binauthz` = false (defaults); Kyverno still enforces signatures |
| secure app won't start | check `kubectl --context secure -n dealsvc describe pod` — usually the image isn't signed yet (`make images-secure`) so Kyverno blocks it; confirm `CI_SIGNER_EMAIL` matches the signer |
| poison "blocked" on secure shows ImagePull, not policy | ensure `make image-poison` pushed to **both** registries (it does by default) |
| SSRF step says "metadata unreachable" locally | expected off-cluster; on the cluster it hits the in-namespace `metadata` service (or pass `--metadata-url`) |
| flood doesn't take the insecure pod down | raise `AGENTS`/`DURATION` (e.g. `make attack-insecure AGENTS=20 DURATION=12`) |
| Spot node preempted mid-talk | rare + brief; set `use_spot=false` in tfvars if you want zero risk |
| swarm refuses the target | it only fires at localhost/private/cluster-local; the make targets port-forward to 127.0.0.1 so this won't happen in normal use |

## 9. What to say (the throughline)
Foundation → supply chain → runtime, each red row mapped to a first principle:
**least privilege, identity boundaries, verifiable provenance, auditability,
resilience, recovery.** Close: *"You don't need a magic scanner — you need
defaults that fail closed."*
