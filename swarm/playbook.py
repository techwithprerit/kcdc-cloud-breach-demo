"""Attack objectives + the deterministic fallback plan.

Each objective maps a real cloud misconfiguration to a stage-legible name. The
LLM commander (llm.py) may re-order or narrate these; if there is no LLM key we
fall back to DEFAULT_PLAN so the demo NEVER depends on the network.
"""

# name -> (title, what it proves, first-principles fix shown in the secure run)
OBJECTIVES = {
    "recon": (
        "Recon",
        "Map the exposed surface of the workload",
        "Least exposure — private ingress, no debug routes",
    ),
    "exfil_env": (
        "Secret exfiltration",
        "Pull DB/LLM/admin secrets from a debug endpoint",
        "No secrets in env dumps; Secret Manager + Workload Identity",
    ),
    "ssrf_metadata": (
        "SSRF -> cloud token theft",
        "Abuse SSRF to steal the workload's GCP token from the metadata server",
        "Egress NetworkPolicy + GKE metadata concealment",
    ),
    "admin_takeover": (
        "Admin takeover",
        "Set every deal to 99% off through an unauthenticated admin route",
        "AuthN/Z on admin; identity boundaries",
    ),
    "sa_pivot": (
        "Lateral movement",
        "Read the auto-mounted k8s ServiceAccount token",
        "automountServiceAccountToken:false + least-privilege RBAC",
    ),
    "backdoor": (
        "Supply-chain backdoor",
        "Hit a backdoor route that exists only in a tampered image",
        "Binary Authorization blocks unsigned/unattested images",
    ),
    "flood": (
        "Availability / DoS",
        "Coordinated flood chokes the service until health checks fail",
        "Rate limits + resource limits + HPA keep it up",
    ),
}

# Order the swarm runs when no LLM commander is available.
DEFAULT_PLAN = [
    "recon",
    "exfil_env",
    "ssrf_metadata",
    "admin_takeover",
    "sa_pivot",
    "backdoor",
    "flood",
]

# Paths the recon step probes.
RECON_WORDLIST = [
    "/", "/health", "/deals", "/deals/search?q=spa",
    "/debug/env", "/fetch?url=http://example.com", "/admin/config",
    "/admin/secrets", "/pwned", "/.git/config", "/actuator/env",
]
