# ============================================================================
# SECURE project only — Workload Identity, Secret Manager, and (optional)
# Binary Authorization + org policies. The insecure project gets none of this.
# ============================================================================

resource "google_service_account" "dealsvc" {
  project      = var.project_secure
  account_id   = "dealsvc-demo"
  display_name = "dealsvc secure workload (least privilege)"
  depends_on   = [google_project_service.svc]
}

resource "google_project_iam_member" "dealsvc_secrets" {
  project = var.project_secure
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.dealsvc.email}"
}

# The Workload Identity pool (PROJECT.svc.id.goog) is created with the WI-enabled
# cluster but takes ~a minute to become usable. Wait, so a fresh apply doesn't race
# the "Identity Pool does not exist" error.
resource "time_sleep" "wi_ready" {
  depends_on      = [google_container_cluster.c, google_container_node_pool.np]
  create_duration = "60s"
}

# Bind k8s SA dealsvc/dealsvc (in the secure cluster) to the GSA.
resource "google_service_account_iam_member" "wi" {
  service_account_id = google_service_account.dealsvc.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_secure}.svc.id.goog[dealsvc/dealsvc]"
  depends_on         = [time_sleep.wi_ready]
}

# Kyverno's admission controller must PULL from Artifact Registry to verify image
# signatures. Under Workload Identity its pod has no GCP identity by default, so we
# give the WI GSA AR-read and let the Kyverno KSA impersonate it. (For strict least
# privilege you'd use a dedicated GSA; reusing keeps the demo simple.)
resource "google_project_iam_member" "gsa_ar_reader" {
  project = var.project_secure
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.dealsvc.email}"
}
resource "google_service_account_iam_member" "wi_kyverno" {
  service_account_id = google_service_account.dealsvc.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_secure}.svc.id.goog[kyverno/kyverno-admission-controller]"
  depends_on         = [time_sleep.wi_ready]
}

resource "google_secret_manager_secret" "db" {
  project   = var.project_secure
  secret_id = "DEMO_DB_PASSWORD"
  replication {
    auto {}
  }
  depends_on = [google_project_service.svc]
}
resource "google_secret_manager_secret_version" "db" {
  secret      = google_secret_manager_secret.db.id
  secret_data = "pr0d-db-Pa55!"
}

resource "google_secret_manager_secret" "admin" {
  project   = var.project_secure
  secret_id = "DEMO_ADMIN_TOKEN"
  replication {
    auto {}
  }
  depends_on = [google_project_service.svc]
}
resource "google_secret_manager_secret_version" "admin" {
  secret      = google_secret_manager_secret.admin.id
  secret_data = "s3cr3t-admin-token"
}

# ---- optional: org policies on the secure project (needs orgpolicy.policyAdmin) ----
locals {
  bool_constraints = [
    "iam.disableServiceAccountKeyCreation",
    "compute.requireShieldedVm",
    "storage.uniformBucketLevelAccess",
  ]
}
resource "google_org_policy_policy" "bool" {
  for_each = var.enable_org_policies ? toset(local.bool_constraints) : toset([])
  name     = "projects/${var.project_secure}/policies/${each.value}"
  parent   = "projects/${var.project_secure}"
  spec {
    rules {
      enforce = "TRUE"
    }
  }
  depends_on = [google_project_service.svc]
}
resource "google_org_policy_policy" "no_external_ip" {
  count  = var.enable_org_policies ? 1 : 0
  name   = "projects/${var.project_secure}/policies/compute.vmExternalIpAccess"
  parent = "projects/${var.project_secure}"
  spec {
    rules {
      deny_all = "TRUE"
    }
  }
  depends_on = [google_project_service.svc]
}

# ---- optional: Binary Authorization attestor + enforce policy on secure project ----
resource "google_container_analysis_note" "note" {
  count   = var.enable_binauthz ? 1 : 0
  project = var.project_secure
  name    = "dealsvc-attestor-note"
  attestation_authority {
    hint {
      human_readable_name = "dealsvc attestor"
    }
  }
  depends_on = [google_project_service.svc]
}
resource "google_binary_authorization_attestor" "attestor" {
  count   = var.enable_binauthz ? 1 : 0
  project = var.project_secure
  name    = "dealsvc-attestor"
  attestation_authority_note {
    note_reference = google_container_analysis_note.note[0].name
  }
}
resource "google_binary_authorization_policy" "secure" {
  count                         = var.enable_binauthz ? 1 : 0
  project                       = var.project_secure
  global_policy_evaluation_mode = "ENABLE"
  admission_whitelist_patterns {
    name_pattern = "registry.k8s.io/**"
  }
  admission_whitelist_patterns {
    name_pattern = "gke.gcr.io/**"
  }
  admission_whitelist_patterns {
    name_pattern = "*.pkg.dev/gke-release/**"
  }
  default_admission_rule {
    evaluation_mode         = "REQUIRE_ATTESTATION"
    enforcement_mode        = "ENFORCED_BLOCK_AND_AUDIT_LOG"
    require_attestations_by = [google_binary_authorization_attestor.attestor[0].name]
  }
}
