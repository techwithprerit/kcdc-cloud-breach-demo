# INSECURE image — the "how did this pass review" build.
#  - fat base image (lots of OS packages = lots of CVEs for the scanner to find)
#  - runs as root
#  - no SBOM, no provenance, no signature (built by cloudbuild-insecure.yaml)
#  - pinned to an OLD patch level on purpose so trivy/grype light up
FROM python:3.11.9-slim-bookworm

# NOTE: Cloud Build (and `minikube image build`) use the REPO ROOT as the build
# context with `-f app/Dockerfile`, so COPY paths are app/-prefixed.
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/main.py .

# root, writable fs, no healthcheck hardening — all deliberate.
EXPOSE 8080
CMD ["python", "main.py"]
