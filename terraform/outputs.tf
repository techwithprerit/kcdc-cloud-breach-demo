output "project_insecure" { value = var.project_insecure }
output "project_secure" { value = var.project_secure }
output "region" { value = var.region }
output "zone" { value = var.zone }
output "gsa_email" { value = google_service_account.dealsvc.email }

# Drop straight into .env:  terraform output -raw env_exports > ../.env
output "env_exports" {
  value = <<-EOT
    export PROJECT_INSECURE=${var.project_insecure}
    export PROJECT_SECURE=${var.project_secure}
    export REGION=${var.region}
    export ZONE=${var.zone}
    export GSA_EMAIL=${google_service_account.dealsvc.email}
    export IMAGE_INSECURE=${var.region}-docker.pkg.dev/${var.project_insecure}/demo/dealsvc:insecure
    export IMAGE_SECURE=${var.region}-docker.pkg.dev/${var.project_secure}/demo/dealsvc:secure
    export IMAGE_POISON=${var.region}-docker.pkg.dev/${var.project_insecure}/demo/dealsvc:poison
    export IMAGE_POISON_SECURE=${var.region}-docker.pkg.dev/${var.project_secure}/demo/dealsvc:poison
  EOT
}
