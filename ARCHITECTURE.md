# Architecture & the vuln → first-principles-fix map

The demo is **one app, two worlds**. The same `dealsvc` container runs in an
insecure GCP project and a secure GCP project. Nothing about the *code* changes
between them — only the **foundation, supply chain, and runtime** configuration.
That is the talk's thesis made physical: breaches come from insecure defaults
and over-trusting architecture, not bad code.

```
                          ┌─────────────────────────────────────────┐
   AI AGENT SWARM  ─────► │  LAYER 1  FOUNDATION                     │
   (LLM commander +       │   project, IAM, VPC, org policy, BinAuthz │
    worker agents)        ├─────────────────────────────────────────┤
        │                 │  LAYER 2  SUPPLY CHAIN                   │
        │  same swarm,     │   image build, SBOM, scan, sign, SLSA    │
        │  two targets     ├─────────────────────────────────────────┤
        ▼                 │  LAYER 3  RUNTIME                        │
   red  → green           │   k8s: identity, network, limits, admission│
                          └─────────────────────────────────────────┘
```

## The swarm (why "agentic")
An LLM **commander** takes live recon of the target and returns an ordered attack
plan + intent narration; **worker agents** execute objectives concurrently and a
subset runs a coordinated flood. Same binary, pointed at each world — so the
scoreboard flips from red to green in front of the room. No LLM key? It drops to
a deterministic playbook so the network can never break the demo. It refuses any
target that isn't localhost / private / cluster-local unless you assert ownership.

---

## Layer 1 — Foundation
| Attack / weakness | Insecure world | First-principles fix (secure world) |
|---|---|---|
| Anything can be deployed | Binary Authorization `ALWAYS_ALLOW` | **Verifiable trust**: `REQUIRE_ATTESTATION` |
| Broad blast radius | primitive/broad IAM, node SA `cloud-platform` | **Least privilege**: dedicated GSA, Workload Identity |
| Data exfil to internet | VMs get external IPs, default VPC | **Boundary**: org policy denies external IP, no default net |
| Key leakage | SA keys allowed | **No standing creds**: `disableServiceAccountKeyCreation` |
| Tamperable nodes | default nodes | **Integrity**: `requireShieldedVm`, secure boot |

## Layer 2 — Supply chain
| Attack / weakness | Insecure world | First-principles fix (secure world) |
|---|---|---|
| CVE-ridden base image | `python:slim` fat base, no scan | **Minimize + gate**: distroless, trivy blocks HIGH/CRITICAL |
| "What's even in this image?" | no SBOM | **Auditability**: syft SPDX SBOM, attached as attestation |
| Can't prove where it came from | no provenance | **Provenance**: SLSA attestation (who/what/how) |
| Tampered/backdoored image ships | unsigned, still runs | **Signing**: cosign keyless (Fulcio + Rekor) |
| Poisoned image reaches prod | no admission gate | **Enforce at the door**: BinAuthz + Kyverno `verifyImages` |

## Layer 3 — Runtime
| Attack / weakness | Insecure world | First-principles fix (secure world) |
|---|---|---|
| Secret exfil via `/debug/env` | secrets in env, debug open | **Least exposure**: Secret Manager + CSI, no debug route |
| SSRF → steal cloud token | `/fetch` hits metadata server | **Egress boundary**: NetworkPolicy deny + GKE metadata concealment |
| Unauth admin → 99% off | `/admin/*` open | **Identity boundary**: authN/Z required |
| Lateral movement | SA token auto-mounted, RBAC reads all secrets | **Least privilege**: `automount:false`, scoped RBAC |
| Run as root, writable FS | no securityContext | **Reduce privilege**: non-root, read-only FS, drop caps, seccomp |
| DoS: one flood = outage | 1 replica, no limits, event-loop starves | **Resilience**: rate limit + limits + HPA + PDB |
| Publicly exposed | `Service type: LoadBalancer` | **Minimize surface**: ClusterIP + internal ingress |

---

## Recovery (the fourth principle)
The whole thing is Terraform + declarative manifests + reproducible signed builds.
Blowing it away and rebuilding is `terraform destroy && terraform apply` + a
pipeline run — which is the point: **auditability and recovery are properties of
the architecture, not heroics during an incident.**
