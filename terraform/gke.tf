# One small, cheap ZONAL cluster per project. Hardened features are switched on
# only for the secure project via the `hardened` flag.
#   insecure: LEGACY datapath, no Workload Identity, node metadata exposed
#   secure  : Dataplane V2 (NetworkPolicy), Workload Identity, GKE metadata hidden, shielded
resource "google_container_cluster" "c" {
  for_each = local.projects

  project                  = each.value.id
  name                     = each.key # "insecure" / "secure"
  location                 = var.zone
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = false

  networking_mode   = "VPC_NATIVE"
  ip_allocation_policy {}
  datapath_provider = each.value.hardened ? "ADVANCED_DATAPATH" : "LEGACY_DATAPATH"
  release_channel { channel = "REGULAR" }

  dynamic "workload_identity_config" {
    for_each = each.value.hardened ? [1] : []
    content { workload_pool = "${each.value.id}.svc.id.goog" }
  }

  dynamic "binary_authorization" {
    for_each = (each.value.hardened && var.enable_binauthz) ? [1] : []
    content { evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE" }
  }

  depends_on = [google_project_service.svc]
}

resource "google_container_node_pool" "np" {
  for_each = local.projects

  project  = each.value.id
  name     = "spot-pool"
  cluster  = google_container_cluster.c[each.key].id
  location = var.zone

  autoscaling {
    min_node_count = 1
    max_node_count = var.node_max
  }
  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type = var.node_machine_type
    spot         = var.use_spot
    disk_size_gb = var.disk_size_gb
    disk_type    = "pd-standard"
    image_type   = "COS_CONTAINERD"
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    dynamic "workload_metadata_config" {
      for_each = each.value.hardened ? [1] : []
      content { mode = "GKE_METADATA" }
    }
    dynamic "shielded_instance_config" {
      for_each = each.value.hardened ? [1] : []
      content {
        enable_secure_boot          = true
        enable_integrity_monitoring = true
      }
    }
    labels = { posture = each.key }
  }
}
