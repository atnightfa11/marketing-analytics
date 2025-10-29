terraform {
  required_version = ">= 1.5.0"
  required_providers {
    fly = {
      source  = "fly-apps/fly"
      version = "~> 0.0.21"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "fly" {
  access_token = var.fly_access_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

resource "random_password" "upload_token_secret" {
  length  = 32
  special = true
}

resource "fly_postgres_cluster" "primary" {
  name                 = "${var.project}-pg"
  organization         = var.fly_org
  region               = var.region
  initial_cluster_size = var.db_size
  vm_size              = "performance-1x"
  password             = random_password.upload_token_secret.result
}

resource "fly_app" "server" {
  name   = "${var.project}-server"
  org_id = var.fly_org
  region = var.region

  services = [{
    internal_port = 8000
    protocol      = "tcp"
    ports = [{
      port     = 443
      handlers = ["tls", "http"]
    }]
  }]
}

resource "fly_app" "alerts" {
  name   = "${var.project}-alerts"
  org_id = var.fly_org
  region = var.region

  services = [{
    internal_port = 8080
    protocol      = "tcp"
    ports = [{
      port     = 443
      handlers = ["tls", "http"]
    }]
  }]
}

resource "fly_app_secret" "server_env" {
  app    = fly_app.server.name
  key    = "DATABASE_URL"
  value  = fly_postgres_cluster.primary.connection_string
}

resource "fly_app_secret" "server_upload_secret" {
  app   = fly_app.server.name
  key   = "UPLOAD_TOKEN_SECRET"
  value = random_password.upload_token_secret.result
}

resource "fly_app_secret" "server_config" {
  app   = fly_app.server.name
  key   = "MIN_REPORTS_PER_WINDOW"
  value = tostring(var.min_reports_per_window)
}

resource "fly_app_secret" "server_ttl" {
  app   = fly_app.server.name
  key   = "UPLOAD_TOKEN_TTL_SECONDS"
  value = tostring(var.upload_token_ttl_seconds)
}

resource "fly_app_secret" "server_flags" {
  app = fly_app.server.name
  key = "LIVE_WATERMARK_SECONDS"
  value = tostring(var.live_watermark_seconds)
}

resource "fly_app_secret" "server_alpha" {
  app   = fly_app.server.name
  key   = "ALPHA_SMOOTHING"
  value = tostring(var.alpha_smoothing)
}

resource "cloudflare_record" "api_cname" {
  zone_id = var.cloudflare_zone_id
  name    = "api.${var.domain}"
  type    = "CNAME"
  value   = fly_app.server.app_id
  proxied = true
}

resource "cloudflare_record" "dashboard_cname" {
  zone_id = var.cloudflare_zone_id
  name    = "dashboard.${var.domain}"
  type    = "CNAME"
  value   = fly_app.server.app_id
  proxied = true
}

output "database_url" {
  description = "Postgres connection string"
  value       = fly_postgres_cluster.primary.connection_string
  sensitive   = true
}

output "api_hostname" {
  description = "Public API hostname"
  value       = cloudflare_record.api_cname.hostname
}
