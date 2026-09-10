# Cost — how this stays cheap

The demo runs in **two existing projects** (`my-insecure-project`, `my-secure-project`), one
small cluster each. Everything is tuned for "very little cost," and the expensive
thing (the clusters) is one command to pause or delete.

## What's billable
| Thing | Choice | Rough cost |
|---|---|---|
| GKE control plane | **zonal** clusters | GKE free tier covers **one** zonal cluster's mgmt fee per billing account; the 2nd is ~**$0.10/hr** while it exists |
| Nodes | 1× **Spot** `e2-standard-2` per cluster | ~**$0.02/hr each** (~70–80% off on-demand) |
| Boot disk | 30 GB **pd-standard** ×2 | pennies/day |
| LoadBalancer | **none** (ClusterIP + port-forward) | **$0** (saves ~$18/mo each) |
| Artifact Registry | a few small images | negligible |
| Cloud Build | 3–4 builds | within the free 120 build-min/day |
| Secret Manager / Binary Auth | tiny / free | ~$0 |

**Realistic total** for building + a rehearsal + the talk (a few hours), then
tearing down: **well under a few dollars.** The number only grows if you leave the
clusters running for days — so pause or delete them.

## The three cost switches
```bash
make pause     # scale BOTH node pools to 0  -> near-zero while idle (keeps config/images)
make resume    # scale BOTH back to 1 node   -> ~2 min before the talk
make down      # delete BOTH clusters        -> stops all compute cost (keeps registries/secrets)
make nuke      # terraform destroy EVERYTHING this demo created
```
Rebuild after `make down` is fast + cheap: `make up && make creds && make deploy`
(images/secrets were kept).

## Cheapest possible workflow
1. `make setup` the day before, rehearse once.
2. `make pause` overnight.
3. `make resume` ~10 min before you present.
4. `make down` (or `make nuke`) the moment you walk off stage.

## Even cheaper: don't touch GCP at all for rehearsal
`make fallback-up` runs the whole attack→defense story on **minikube** locally
(runtime layer + SSRF via a fake metadata server). Zero cloud cost. Keep GCP for
the live run only. See `fallback-minikube/`.

## Knobs (terraform.tfvars)
`node_machine_type`, `use_spot`, `node_max`, `disk_size_gb` — all set cheap by
default. Set `use_spot = false` only if you're worried about a (rare, brief)
Spot preemption mid-talk.
