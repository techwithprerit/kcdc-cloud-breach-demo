# Offline fallback (minikube)

Your insurance policy for a bad venue network or a GCP hiccup. Same app, same
agent swarm, same red→green story — entirely on your laptop. The **runtime**
layer (root vs non-root, no-limits vs limits+HPA, mounted SA token, over-broad
RBAC, default-deny NetworkPolicy) and the **SSRF → token theft** are all shown
here via an in-cluster fake metadata server. The **supply-chain** layer
(SBOM/SLSA/signing/Binary Authorization) is GCP-only — if you fall back, narrate
it from the slides / `ARCHITECTURE.md` table.

## Prereqs
`minikube`, `kubectl`, Docker/podman, Python 3.11+, and the swarm deps:
```
pip install -r swarm/requirements.txt      # httpx, rich  (+ anthropic for LLM mode)
```

## Run
```
bash fallback-minikube/setup.sh            # start minikube, build image, apply insecure stack
```
Then follow the two-terminal instructions it prints:
1. `port-forward` the insecure app, run the swarm → scoreboard goes **red**.
2. `kubectl apply -f fallback-minikube/10-secure.yaml`, port-forward it, re-run
   the swarm → scoreboard goes **green**.

## Notes
- `--cni=calico` is required so `NetworkPolicy` is actually enforced (minikube's
  default CNI ignores it, which would quietly break the SSRF-dead-end demo).
- The DoS is visible as pod restarts: `watch -n1 kubectl -n demo-insecure get pods`.
- No LLM key? The swarm runs in deterministic offline mode automatically.
