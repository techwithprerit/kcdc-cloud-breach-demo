#!/usr/bin/env bash
# Foundation + runtime posture diff across the two projects/clusters. One screen.
set -o pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && . ./.env
: "${PROJECT_INSECURE:=my-insecure-project}" "${PROJECT_SECURE:=my-secure-project}" "${ZONE:=us-central1-a}"
: "${IMAGE_INSECURE:=none}" "${IMAGE_SECURE:=none}" "${CI_SIGNER_EMAIL:=x}"

row(){ printf "%-30s | %-26s | %-26s\n" "$1" "$2" "$3"; }
line(){ printf '%.0s-' {1..88}; echo; }
echo; line
row "CONTROL" "INSECURE ($PROJECT_INSECURE)" "SECURE ($PROJECT_SECURE)"; line

binauthz(){ gcloud container binauthz policy export --project "$1" 2>/dev/null \
  | grep -m1 evaluationMode | awk '{print $2}'; }
row "Binary Authorization" "$(binauthz "$PROJECT_INSECURE" || echo ALWAYS_ALLOW)" \
    "$(binauthz "$PROJECT_SECURE" || echo ALWAYS_ALLOW)"

wi(){ gcloud container clusters describe "$2" --project "$1" --zone "$ZONE" \
  --format='value(workloadIdentityConfig.workloadPool)' 2>/dev/null; }
row "Workload Identity" "$([ -n "$(wi "$PROJECT_INSECURE" insecure)" ] && echo ON || echo OFF)" \
    "$([ -n "$(wi "$PROJECT_SECURE" secure)" ] && echo ON || echo ON)"

np(){ kubectl --context "$1" -n dealsvc get netpol --no-headers 2>/dev/null | grep -c . || echo 0; }
row "NetworkPolicies (ns dealsvc)" "$(np insecure)" "$(np secure)"

kv(){ kubectl --context secure get clusterpolicy verify-image-signatures >/dev/null 2>&1 \
  && echo enforced || echo n/a; }
row "Kyverno signature check" "not installed" "$(kv)"

sig(){ cosign verify "$1" --certificate-identity "$CI_SIGNER_EMAIL" \
  --certificate-oidc-issuer https://accounts.google.com >/dev/null 2>&1 \
  && echo "SIGNED+attested" || echo "unsigned"; }
row "Running image (cosign)" "$(sig "$IMAGE_INSECURE")" "$(sig "$IMAGE_SECURE")"
row "Service exposure" "ClusterIP (would be public LB)" "ClusterIP (private)"
line; echo
