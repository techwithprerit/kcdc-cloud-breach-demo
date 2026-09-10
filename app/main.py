"""
dealsvc — a deliberately vulnerable "Groupon-style" deals API.

The SAME image runs in both the insecure and the secure demo. Behavior is
toggled by environment variables so that the difference the audience sees is
CONFIGURATION, not code. That is the whole thesis of the talk: breaches come
from insecure defaults and over-trusting architecture, not "bad code".

Security toggles (all default to the INSECURE value = off):
  SECURE_DEBUG=1       -> /debug/env returns 404 instead of dumping os.environ
  SECURE_SSRF=1        -> /fetch validates the URL (no link-local / metadata)
  SECURE_ADMIN=1       -> /admin/* requires  Authorization: Bearer $ADMIN_TOKEN
  SECURE_RATELIMIT=1   -> token-bucket per client IP -> 429 under flood
  EXPENSIVE_OFFLOAD=1  -> /deals/search runs in a threadpool (event loop stays alive)

Supply-chain toggle (baked into the *poisoned* image, never the clean one):
  BACKDOOR=1           -> exposes /pwned proving code execution from a tampered image

Secrets are provided via env in the insecure deployment (plain values in the
manifest) and via Secret Manager / k8s Secret in the secure deployment. The
values are identical; what changes is whether an attacker can pull them back
out through /debug/env.
"""
from __future__ import annotations

import os
import socket
import time
import ipaddress
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool


def flag(name: str) -> bool:
    return os.environ.get(name, "0").lower() in ("1", "true", "yes", "on")


APP_NAME = os.environ.get("APP_NAME", "dealsvc")
VERSION = os.environ.get("APP_VERSION", "1.0.0")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

app = FastAPI(title=APP_NAME, version=VERSION)

# ---------------------------------------------------------------------------
# Mutable "business config" — an attacker who reaches /admin can move money.
# ---------------------------------------------------------------------------
STATE = {"discount_pct": 10, "requests": 0, "compromised": False}

# In-memory catalog. discount_pct is applied at read time so an admin takeover
# is instantly visible in /deals — the "all deals are now 99% off" moment.
DEALS = [
    {"id": 1, "title": "Weekend Spa Package", "price": 199.0},
    {"id": 2, "title": "Sushi Masterclass for Two", "price": 89.0},
    {"id": 3, "title": "Skydiving Experience", "price": 299.0},
    {"id": 4, "title": "City Rooftop Brunch", "price": 45.0},
]

# ---------------------------------------------------------------------------
# Rate limiting (token bucket, per client IP). Only enforced when SECURE_RATELIMIT=1.
# ---------------------------------------------------------------------------
_BUCKET: dict[str, list[float]] = {}
_CAP = float(os.environ.get("RL_CAPACITY", "20"))
_REFILL = float(os.environ.get("RL_REFILL_PER_SEC", "10"))


def _allow(ip: str) -> bool:
    now = time.monotonic()
    tokens, last = _BUCKET.get(ip, (_CAP, now))
    tokens = min(_CAP, tokens + (now - last) * _REFILL)
    if tokens < 1:
        _BUCKET[ip] = (tokens, now)
        return False
    _BUCKET[ip] = (tokens - 1, now)
    return True


@app.middleware("http")
async def _mw(request: Request, call_next):
    STATE["requests"] += 1
    if flag("SECURE_RATELIMIT") and request.url.path.startswith("/deals"):
        ip = request.client.host if request.client else "unknown"
        if not _allow(ip):
            return JSONResponse({"error": "rate limited"}, status_code=429)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    routes = ["/health", "/deals", "/deals/search?q=", "/admin/config", "/admin/secrets"]
    if not flag("SECURE_DEBUG"):
        routes.append("/debug/env")
    if not flag("SECURE_SSRF"):
        routes.append("/fetch?url=")
    if flag("BACKDOOR"):
        routes.append("/pwned")
    return {"service": APP_NAME, "version": VERSION, "host": socket.gethostname(), "routes": routes}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready"}


@app.get("/deals")
def deals():
    d = STATE["discount_pct"] / 100.0
    return {
        "discount_pct": STATE["discount_pct"],
        "compromised": STATE["compromised"],
        "deals": [{**x, "sale_price": round(x["price"] * (1 - d), 2)} for x in DEALS],
    }


_EXPENSIVE_ITERS = int(os.environ.get("EXPENSIVE_ITERS", "4000000"))  # ~200ms/call


def _expensive_blocking(q: str) -> int:
    # CPU-bound work. In an *async* route with no await this starves the single
    # event loop, so /health starts timing out under a flood -> liveness restart.
    # Realistic footgun: heavy sync work on the request path with no rate limit.
    total = 0
    for i in range(1, _EXPENSIVE_ITERS):
        total += (i ^ len(q)) % 7
    return total


@app.get("/deals/search")
async def search(q: str = "laptop"):
    if flag("EXPENSIVE_OFFLOAD"):
        score = await run_in_threadpool(_expensive_blocking, q)  # bounded, off the loop
    else:
        score = _expensive_blocking(q)  # blocks the event loop
    hits = [x for x in DEALS if q.lower() in x["title"].lower()]
    return {"q": q, "score": score, "results": hits}


# ---------------------------------------------------------------------------
# VULN 1 — secret exposure via a debug endpoint (insecure default)
# ---------------------------------------------------------------------------
@app.get("/debug/env")
def debug_env():
    if flag("SECURE_DEBUG"):
        return JSONResponse({"error": "not found"}, status_code=404)
    # Leaks EVERYTHING: DB_PASSWORD, LLM_API_KEY, ADMIN_TOKEN, cloud creds...
    return dict(os.environ)


# ---------------------------------------------------------------------------
# VULN 2 — SSRF. The app fetches an attacker-controlled URL server-side.
# Pointed at the cloud metadata server this steals the workload's GCP token.
# ---------------------------------------------------------------------------
def _is_dangerous(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True
    if host in ("metadata.google.internal", "metadata"):
        return True
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_private or ip.is_link_local or ip.is_loopback
    except Exception:
        return False  # can't resolve; let httpx fail normally


@app.get("/fetch")
async def fetch(url: str, h: str | None = None):
    if flag("SECURE_SSRF"):
        if urlparse(url).scheme not in ("http", "https") or _is_dangerous(url):
            return JSONResponse({"error": "blocked by egress policy"}, status_code=403)
    headers = {}
    # An "innocent" app helpfully forwards a caller-supplied header (e.g. so it
    # can read cloud metadata). h="Metadata-Flavor:Google"
    if h and ":" in h:
        k, v = h.split(":", 1)
        headers[k.strip()] = v.strip()
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(url, headers=headers)
        return PlainTextResponse(r.text[:4000], status_code=r.status_code)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


# ---------------------------------------------------------------------------
# VULN 3 — unauthenticated admin (insecure default)
# ---------------------------------------------------------------------------
def _admin_ok(authorization: str | None) -> bool:
    if not flag("SECURE_ADMIN"):
        return True
    return bool(ADMIN_TOKEN) and authorization == f"Bearer {ADMIN_TOKEN}"


@app.post("/admin/config")
async def admin_config(request: Request, authorization: str | None = Header(default=None)):
    if not _admin_ok(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    if "discount_pct" in body:
        STATE["discount_pct"] = int(body["discount_pct"])
        STATE["compromised"] = True
    return {"ok": True, "discount_pct": STATE["discount_pct"]}


@app.get("/admin/secrets")
def admin_secrets(authorization: str | None = Header(default=None)):
    if not _admin_ok(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    out = {"db_password": os.environ.get("DB_PASSWORD", ""),
           "llm_api_key": os.environ.get("LLM_API_KEY", "")}
    # VULN 4 — the ServiceAccount token is auto-mounted; hand it over.
    try:
        with open(SA_TOKEN_PATH) as f:
            tok = f.read().strip()
        out["k8s_sa_token"] = tok[:24] + "...(" + str(len(tok)) + " bytes)"
        out["lateral_movement"] = "SA token mounted & readable -> can call the k8s API"
    except Exception:
        out["k8s_sa_token"] = None
        out["lateral_movement"] = "no SA token mounted (automountServiceAccountToken:false)"
    return out


# ---------------------------------------------------------------------------
# Supply-chain proof — only present in the POISONED image (BACKDOOR=1).
# Benign: it just proves code execution reached the cluster from a tampered build.
# ---------------------------------------------------------------------------
if flag("BACKDOOR"):
    @app.get("/pwned")
    def pwned():
        return {"backdoor": True, "uname": " ".join(os.uname()),
                "note": "This route exists ONLY because a tampered image was admitted."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")))
