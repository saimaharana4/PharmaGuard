variable "project_id" {
  type        = string
  description = "Existing Google Cloud project; no new project is provisioned."
}

variable "region" {
  type        = string
  description = "Region for the retained VM network and registry."
}

variable "zone" {
  type        = string
  description = "Zone containing the retained application VM."
}

variable "machine_type" {
  type        = string
  description = "Retained VM size; upgrades require an explicit reviewed plan."
}

variable "expires_at" {
  type        = string
  description = "UTC stop deadline; preserve the VM and its disk."
}

variable "runtime_secret_ids" {
  type        = set(string)
  description = "Explicit Secret Manager IDs readable by the VM runtime identity."
}
