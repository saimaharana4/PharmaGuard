module "application_vm" {
  source             = "../../modules/application_vm"
  project_id         = var.project_id
  region             = var.region
  zone               = var.zone
  machine_type       = var.machine_type
  expires_at         = var.expires_at
  runtime_secret_ids = var.runtime_secret_ids
}

output "instance_name" {
  description = "Retained application instance name."
  value       = module.application_vm.instance_name
}
output "internal_ip" {
  description = "Private VM address; no public application listener."
  value       = module.application_vm.internal_ip
}
output "network" {
  description = "Existing application VPC name."
  value       = module.application_vm.network
}
output "edge_subnet" {
  description = "Production HTTPS edge source subnet."
  value       = module.application_vm.edge_subnet
}
