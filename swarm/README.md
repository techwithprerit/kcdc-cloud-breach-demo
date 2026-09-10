# The agent swarm

An LLM-commanded red-team swarm. It runs the **same** against every target — the
cluster is what changes — so it's the instrument that flips the scoreboard.

## Run
```bash
pip install -r requirements.txt        # httpx, rich  (+ anthropic/openai for LLM mode)
python swarm.py --target http://127.0.0.1:8080 --label insecure
python swarm.py --target http://127.0.0.1:8081 --label secure
```

## How it's agentic
1. **Recon** the target (live).
2. An **LLM commander** (`llm.py`) turns that recon into an ordered attack plan +
   an intent line in the operator's voice.
3. **Worker agents** execute objectives concurrently; a subset runs a coordinated
   flood while a probe measures whether the service stays up.
4. A **scoreboard** + **breach report** render the result.

No `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`? It runs a deterministic playbook — the
demo never depends on the network. Set one to make it genuinely LLM-planned.

## Objectives
`recon · exfil_env · ssrf_metadata · admin_takeover · sa_pivot · backdoor · flood`
(see `playbook.py`; each maps to a fix in `../ARCHITECTURE.md`).

## Flags
| Flag | Meaning |
|---|---|
| `--target` | base URL of the app you own |
| `--label` | scoreboard label (`insecure`/`secure`) |
| `--agents` / `--duration` | flood concurrency / seconds |
| `--allow` + `SWARM_I_OWN_THIS=1` | authorize a public IP you own |
| `--metadata-url` | SSRF target (offline fake metadata server) |
| `--gcs-bucket` | bucket to test the stolen token against |

## Safety
Refuses any target that isn't localhost / private / `*.svc` unless you explicitly
assert ownership. The "exploits" hit misconfigured endpoints on the app this repo
ships and flood it — no CVE weaponry, no malware. Authorized use only.

## Test
```bash
python - <<'PY'
import swarm
print(swarm.flood_verdict(p95=6200, err_rate=38, rl_rate=0, health_fail=0.62))  # -> breached
print(swarm.flood_verdict(p95=140, err_rate=1, rl_rate=61, health_fail=0.0))    # -> held
PY
```
