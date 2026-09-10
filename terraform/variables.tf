# Two EXISTING projects you own. Terraform never creates or deletes the projects —
# it only adds resources inside them, and leaves APIs enabled on destroy.
# REQUIRED: set these in terraform.tfvars (no defaults, so you can't accidentally
# target someone else's project).
variable "project_insecure" {
  description = "Your GCP project ID for the INSECURE world."
  type        = string
}

variable "project_secure" {
  description = "Your GCP project ID for the SECURE world."
  type        = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  description = "Single zone -> ZONAL clusters (cheapest control plane)."
  type        = string
  default     = "us-central1-a"
}

# ---- cost knobs (defaults chosen for 'very little cost' per project) ----
variable "node_machine_type" {
  type    = string
  default = "e2-standard-2" # 2 vCPU / 8 GB — enough for app + (secure) Kyverno on ONE node
}

variable "use_spot" {
  description = "Spot VMs ~70-80% cheaper. Fine for a demo."
  type        = bool
  default     = true
}

variable "node_max" {
  type    = number
  default = 2
}

variable "disk_size_gb" {
  type    = number
  default = 30
}

# ---- optional hardening that needs elevated permissions; off by default so a
#      plain `apply` never fails on IAM. Turn on if you have the roles. ----
variable "enable_org_policies" {
  description = "Set org-policy constraints on the secure project (needs orgpolicy.policyAdmin)."
  type        = bool
  default     = false
}

variable "enable_binauthz" {
  description = "Create a Binary Authorization attestor+policy on the secure project. Kyverno enforces signatures either way."
  type        = bool
  default     = false
}

variable "ci_signer_email" {
  description = "cosign keyless subject (the secure project's Cloud Build SA). Set after first build."
  type        = string
  default     = ""
}
