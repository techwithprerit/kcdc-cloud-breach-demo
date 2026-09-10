# The two worlds. Same resources in each project; the SECURE one gets extra
# hardening (Workload Identity, Dataplane V2, GKE metadata concealment, secrets,
# optional Binary Authorization / org policies). Projects must already exist.

locals {
  projects = {
    insecure = { id = var.project_insecure, hardened = false }
    secure   = { id = var.project_secure, hardened = true }
  }
  apis = [
    "compute.googleapis.com",
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "containeranalysis.googleapis.com",
    "binaryauthorization.googleapis.com",
    "iam.googleapis.com",
    "orgpolicy.googleapis.com",
  ]
}

resource "google_project_service" "svc" {
  for_each = {
    for pair in setproduct(keys(local.projects), local.apis) :
    "${pair[0]}:${pair[1]}" => { project = local.projects[pair[0]].id, api = pair[1] }
  }
  project            = each.value.project
  service            = each.value.api
  disable_on_destroy = false # never disturb the existing projects on teardown
}

resource "google_artifact_registry_repository" "demo" {
  for_each      = local.projects
  project       = each.value.id
  location      = var.region
  repository_id = "demo"
  format        = "DOCKER"
  depends_on    = [google_project_service.svc]
}
