#!/usr/bin/env bash
# Run the morning of the talk. Reports readiness; never aborts mid-way.
set -o pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
ok=0; bad=0
chk(){ if eval "$2" >/dev/null 2>&1; then echo "  ✓ $1"; ok=$((ok+1)); else echo "  ✗ $1"; bad=$((bad+1)); fi; }

echo "== tooling =="
chk "gcloud present"    "command -v gcloud"
chk "kubectl present"   "command -v kubectl"
chk "terraform present" "command -v terraform"
chk "cosign present"    "command -v cosign"
chk "envsubst present"  "command -v envsubst"
chk "python present"    "command -v python3 || command -v python"

echo "== env  (populate .env from: make env > .env) =="
for v in PROJECT_INSECURE PROJECT_SECURE IMAGE_INSECURE IMAGE_SECURE IMAGE_POISON CI_SIGNER_EMAIL; do
  chk "$v set" "[ -n \"\${$v:-}\" ]"; done

echo "== clusters reachable =="
chk "insecure context" "kubectl --context insecure get ns"
chk "secure context"   "kubectl --context secure get ns"

echo "== workloads (namespace dealsvc) =="
chk "insecure app ready" "kubectl --context insecure -n dealsvc rollout status deploy/dealsvc --timeout=5s"
chk "secure app ready"   "kubectl --context secure   -n dealsvc rollout status deploy/dealsvc --timeout=5s"
chk "kyverno running (secure)" "kubectl --context secure -n kyverno get deploy kyverno-admission-controller"
chk "signature policy present" "kubectl --context secure get clusterpolicy verify-image-signatures"

echo "== supply chain =="
chk "secure image signed" 'cosign verify "${IMAGE_SECURE:-}" --certificate-identity "${CI_SIGNER_EMAIL:-}" --certificate-oidc-issuer https://accounts.google.com'
chk "poison image unsigned (expected)" '! cosign verify "${IMAGE_POISON:-}" --certificate-identity "${CI_SIGNER_EMAIL:-}" --certificate-oidc-issuer https://accounts.google.com'

echo
echo "PASS=$ok  FAIL=$bad"
if [ "$bad" -eq 0 ]; then
  echo "READY ✅"
else
  echo "NOT READY ❌  — order: install tooling -> make up -> make env > .env (+CI_SIGNER_EMAIL)"
  echo "               -> make images -> make creds -> make deploy -> make preflight"
fi
exit 0
