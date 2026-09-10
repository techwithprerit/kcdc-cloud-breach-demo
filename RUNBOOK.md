# 🎤 The 15-minute stage runbook

Everything heavy is provisioned before you walk up (see `SETUP.md`). On stage you
run short `make` verbs. Two projects, two clusters, contexts named `insecure` /
`secure`. No LoadBalancers — the attack targets go through an auto port-forward
inside the make target.

**Screen layout:** left = your terminal; right = `make watch` (pods on both
clusters). Font 18pt+.

**Pre-flight (before you start):** `make resume` (if paused) then `make preflight`
→ must read **READY ✅**.

---

## Act I — Two worlds (0:00–1:30)
**Say:** *"Same app, same code, two GCP projects. The only difference is the
architecture around it."*
```bash
make posture
```
Call out: Binary Authorization / Workload Identity / NetworkPolicies / Kyverno
signature check / running-image signature — insecure ✗ vs secure ✓.
**Say:** *"Nobody wrote insecure code. Someone accepted insecure defaults."*

---

## Act II — The swarm breaks the insecure world (1:30–5:30)
**Say:** *"A swarm of AI agents. An LLM plans the attack from what it sees; the
workers execute."*
```bash
make attack-insecure
```
Narrate the scoreboard going **red**:
- 🔓 **Secret exfiltration** — `/debug/env` hands over DB + LLM + admin creds.
- 🔑 **SSRF → cloud token** — the app fetches the metadata server *for* the attacker.
- 💸 **Admin takeover** — every deal is now **99% off**. *"There's your $1M."*
- **Lateral movement** — auto-mounted SA token, RBAC reads every secret.
- **Availability** — the flood starves the event loop; glance right → pod **restarting**.

**Say:** *"Six defaults. One swarm. Total compromise in under a minute."*

---

## Act III — Supply chain: the poisoned image (5:30–9:00)
**Say:** *"Now the attacker doesn't break in — they ship you a build."*
```bash
make supplychain
```
Audience sees:
1. `verify.sh` the **signed** image → **✓ signature ✓ SBOM ✓ SLSA provenance**.
2. `verify.sh` the **poison** image → **✗ ✗ ✗**.
3. Poison → **insecure** cluster: **runs** (`kubectl --context insecure -n dealsvc get pods`).
4. Poison → **secure** cluster: **denied** — *"blocked by Kyverno: image not signed
   by the required identity"* (this is Binary Authorization's job, done in-cluster).

**Say:** *"The secure cluster didn't scan and guess. It refused to run anything it
couldn't prove the origin of. SBOM = what's inside; SLSA = where it came from."*

---

## Act IV — The swarm bounces off the secure world (9:00–13:00)
```bash
make attack-secure
```
Same swarm, each row goes **green**:
- Secret exfil → `/debug/env` **404** (secrets in Secret Manager).
- SSRF → **blocked**: egress NetworkPolicy + GKE metadata concealment.
- Admin → **401**.
- Lateral movement → **no token mounted**, scoped RBAC.
- Availability → flood met with **429s**, HPA + limits absorb it; **no restarts**.

**Say:** *"Identical attack. The architecture just says no, five times."*

---

## Act V — The map (13:00–15:00)
Put up `ARCHITECTURE.md` / the diagram. Trace each red row to its principle:
**least privilege, identity boundaries, verifiable provenance, auditability,
resilience, recovery.**
**Close:** *"You don't need a magic scanner. You need defaults that fail closed."*

---

### Reset between rehearsals
```bash
kubectl --context insecure -n dealsvc rollout restart deploy/dealsvc
kubectl --context insecure -n dealsvc delete deploy dealsvc-v2 --ignore-not-found
kubectl --context secure   -n dealsvc delete deploy dealsvc-v2 --ignore-not-found
make pause     # stop paying between runs;  make resume before the next one
```

### If the venue network / GCP fails
`make fallback-up` — Acts II & IV run identically on minikube (runtime layer +
SSRF via a fake metadata server). Narrate Act III from the rehearsal `verify.sh`
output + the architecture table. See `fallback-minikube/README.md`.
