variable "project_id" {
  type        = string
  description = "Existing Google Cloud project ID."
}
variable "region" {
  type        = string
  description = "Region for existing deployment resources."
  default     = "asia-south1"
}
variable "zone" {
  type        = string
  description = "Zone for the retained VM."
  default     = "asia-south1-a"
}
variable "machine_type" {
  type        = string
  description = "Retained VM size; do not resize automatically."
  default     = "e2-standard-2"
}
variable "runtime_secret_ids" {
  description = "Explicit runtime secret IDs, scoped individually through IAM."
  type        = set(string)
  default = ["pg-config-runtime", "pg-runtime-db-password", "pg-qdrant-api-key",
  "pg-groq-api-key", "pg-openai-api-key", "pg-session-signing-key"]
}
variable "expires_at" {
  type        = string
  description = "Stop at the deployment expiry, preserving VM and disk. UTC."
  default     = "2026-11-19T18:30:00Z"
  validation {
    condition     = can(formatdate("YYYY-MM-DD", var.expires_at))
    error_message = "Use an RFC3339 expiry timestamp."
  }
}
