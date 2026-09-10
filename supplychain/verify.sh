#!/usr/bin/env bash
# The live "prove it" step. Run against BOTH images to show the difference:
#   ./verify.sh "$IMAGE_SECURE"   -> signature ✓  SBOM ✓  SLSA provenance ✓
#   ./verify.sh "$IMAGE_POISON"   -> nothing to verify: unsigned, unattested
#
# Requires: cosign v2+.  CI_SIGNER_EMAIL = the identity your pipeline signs as
# (the Cloud Build SA), and it is what the cluster's attestor pins.
set -uo pipefail
IMG="${1:?usage: verify.sh <image[:tag|@digest]>}"
ISSUER="${COSIGN_ISSUER:-https://accounts.google.com}"
SUBJECT="${CI_SIGNER_EMAIL:?set CI_SIGNER_EMAIL to the signing identity}"

echo "== Target image: $IMG"
echo
echo "== 1) Signature (cosign keyless, Fulcio + Rekor) ============================="
cosign verify "$IMG" \
  --certificate-identity "$SUBJECT" \
  --certificate-oidc-issuer "$ISSUER" >/dev/null 2>&1 \
  && echo "   ✓ SIGNED by $SUBJECT" \
  || { echo "   ✗ NO valid signature — this image would be BLOCKED at admission"; }

echo
echo "== 2) SBOM attestation (SPDX) ================================================"
cosign verify-attestation "$IMG" --type spdxjson \
  --certificate-identity "$SUBJECT" --certificate-oidc-issuer "$ISSUER" >/dev/null 2>&1 \
  && echo "   ✓ SBOM present and attested" \
  || echo "   ✗ NO SBOM attestation"

echo
echo "== 3) SLSA provenance attestation ============================================"
cosign verify-attestation "$IMG" --type slsaprovenance \
  --certificate-identity "$SUBJECT" --certificate-oidc-issuer "$ISSUER" >/dev/null 2>&1 \
  && echo "   ✓ SLSA provenance present and attested (who/what/how it was built)" \
  || echo "   ✗ NO provenance — you cannot prove where this image came from"
echo
