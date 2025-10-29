variable "project" {
  description = "Project slug used for resource names"
  type        = string
}

variable "region" {
  description = "Fly.io region code"
  type        = string
  default     = "iad"
}

variable "db_size" {
  description = "Fly Postgres node size"
  type        = number
  default     = 1
}

variable "fly_org" {
  description = "Fly.io organization ID"
  type        = string
}

variable "fly_access_token" {
  description = "Fly.io API token"
  type        = string
  sensitive   = true
}

variable "domain" {
  description = "Primary marketing analytics domain"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone identifier"
  type        = string
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token for DNS updates"
  type        = string
  sensitive   = true
}

variable "min_reports_per_window" {
  description = "Minimum privatized reports required before publishing a window"
  type        = number
  default     = 40
}

variable "upload_token_ttl_seconds" {
  description = "Default TTL for upload tokens"
  type        = number
  default     = 900
}

variable "live_watermark_seconds" {
  description = "Late arrival tolerance for live windows"
  type        = number
  default     = 120
}

variable "max_out_of_order_seconds" {
  description = "Maximum allowed lateness before dropping reports"
  type        = number
  default     = 300
}

variable "alpha_smoothing" {
  description = "Bayesian smoothing alpha parameter"
  type        = number
  default     = 0.5
}
