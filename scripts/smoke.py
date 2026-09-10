#!/usr/bin/env python3
"""Self-contained smoke test orchestrated from one foreground process."""
import os, subprocess, sys, time, urllib.request, signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv/bin/python")
SEC = dict(DB_PASSWORD="pr0d-db-Pa55!", LLM_API_KEY="sk-DEMO-not-a-real-key", ADMIN_TOKEN="s3cr3t-admin")

def start(port, extra):
    env = {**os.environ, **SEC, "PORT": str(port), **extra}
    return subprocess.Popen([PY, os.path.join(ROOT, "app/main.py")], env=env,
                            stdout=open(f"/tmp/app-{port}.log", "w"), stderr=subprocess.STDOUT)

def wait_health(port, tries=30):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
            return True
        except Exception:
            time.sleep(0.5)
    return False

def swarm(label, port, agents, duration):
    with open(f"/tmp/swarm-{label}.txt", "w") as out:
        subprocess.run([PY, os.path.join(ROOT, "swarm/swarm.py"),
                        "--target", f"http://127.0.0.1:{port}", "--label", label,
                        "--agents", str(agents), "--duration", str(duration)],
                       cwd=os.path.join(ROOT, "swarm"), stdout=out, stderr=subprocess.STDOUT,
                       env={**os.environ, "COLUMNS": "100"})
    print(f"wrote /tmp/swarm-{label}.txt", flush=True)

ins = start(8080, {})
sec = start(8081, dict(SECURE_DEBUG="1", SECURE_SSRF="1", SECURE_ADMIN="1",
                       SECURE_RATELIMIT="1", EXPENSIVE_OFFLOAD="1"))
try:
    ok = wait_health(8080) and wait_health(8081)
    print("both apps healthy:", ok, flush=True)
    if ok:
        swarm("insecure", 8080, 12, 7)
        swarm("secure", 8081, 12, 7)
finally:
    for p in (ins, sec):
        p.send_signal(signal.SIGTERM)
    time.sleep(1)
print("\nSMOKE_DONE", flush=True)
