# Egress Gateway Governance Module
# This file provisions the regional network_attachment and agent_gateway,
# the regional authzExtensions resource configured to REQUEST_AUTHZ,
# and attaches the authz policy to the newly created gateway.

# PSC-Interface network attachment in the private subnet. This is what the Agent Gateway
# egresses through to reach the customer VPC.
resource "google_compute_network_attachment" "agent_gateway" {
  name                  = "${var.agent_gateway_name}-services-na"
  region                = var.region
  connection_preference = "ACCEPT_AUTOMATIC"
  subnetworks           = [var.private_subnet_id]
}


# The Agent Gateway itself. Google-managed, MCP, AGENT_TO_ANYWHERE.
resource "google_network_services_agent_gateway" "agent_gateway" {
  provider  = google-beta
  project   = var.project_id
  name      = var.agent_gateway_name
  location  = var.region
  # protocols = ["MCP"]

  google_managed {
    governed_access_path = "AGENT_TO_ANYWHERE"
  }

  registries = ["//agentregistry.googleapis.com/projects/${var.project_id}/locations/${var.region}"]

  network_config {
    egress {
      network_attachment = google_compute_network_attachment.agent_gateway.id
    }
  }
}

# Allow the Agent Gateway control plane to stabilize before attaching authz policies
resource "time_sleep" "wait_for_gateway" {
  depends_on      = [google_network_services_agent_gateway.agent_gateway]
  create_duration = "30s"
}

# Create the Authz Service Extension for delegated verification
resource "google_network_services_authz_extension" "iap_authz_extension" {
  name              = "${var.agent_gateway_name}-iap-ext"
  location          = var.region
  service           = "iap.googleapis.com"
  timeout           = "3s"
  fail_open         = false
  forward_headers   = ["Authorization", "X-Goog-User-Project"]

  metadata = {
    iapPolicyVersion   = "V1"
    iamEnforcementMode = var.enable_iap_enforcement ? null : "DRY_RUN"
  }
}

# Attach an Authz Policy to bind them together
resource "google_network_security_authz_policy" "egress_authz_policy" {
  depends_on     = [time_sleep.wait_for_gateway]
  provider       = google-beta
  name           = "${var.agent_gateway_name}-iap-policy"
  location       = var.region
  policy_profile = "REQUEST_AUTHZ"
  action         = "CUSTOM"
  
  target {
    resources = [google_network_services_agent_gateway.agent_gateway.id]
  }
  
  # Enable strict IAP authentication & authorization enforcement
  custom_provider {
    authz_extension {
      resources = [google_network_services_authz_extension.iap_authz_extension.id]
    }
  }
}

# Model Armor CONTENT_AUTHZ service extension. Regional REP endpoint.
# The extension passes the request/response templates as opaque metadata.
resource "google_network_services_authz_extension" "model_armor" {
  count    = var.enable_model_armor ? 1 : 0
  provider = google-beta
  project  = var.project_id
  name     = "${var.agent_gateway_name}-ma-authz"
  location = var.region
  service  = "modelarmor.${var.region}.rep.googleapis.com"
  timeout  = "3s"

  metadata = {
    "model_armor_settings" = jsonencode([{
      request_template_id  = "projects/${var.project_id}/locations/${var.region}/templates/${var.model_armor_request_template_id}"
      response_template_id = "projects/${var.project_id}/locations/${var.region}/templates/${var.model_armor_response_template_id}"
    }])
  }
}

# Bind the Model Armor authz extension to the Agent Gateway. CONTENT_AUTHZ
# profile streams body events to the extension for content sanitization.
resource "google_network_security_authz_policy" "model_armor" {
  depends_on     = [time_sleep.wait_for_gateway]
  count          = var.enable_model_armor ? 1 : 0
  provider       = google-beta
  project        = var.project_id
  name           = "${var.agent_gateway_name}-ma-policy"
  location       = var.region
  policy_profile = "CONTENT_AUTHZ"
  action         = "CUSTOM"

  target {
    resources = [google_network_services_agent_gateway.agent_gateway.id]
  }

  custom_provider {
    authz_extension {
      resources = [google_network_services_authz_extension.model_armor[0].id]
    }
  }
}

# IAM for the gateway's service-extensions service account to communicate with Model Armor.
locals {
  service_extensions_sa_member = "serviceAccount:${google_network_services_agent_gateway.agent_gateway.agent_gateway_card[0].service_extensions_service_account}"

  model_armor_sa_roles = var.enable_model_armor ? [
    "roles/modelarmor.calloutUser",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/modelarmor.user",
  ] : []
}

resource "google_project_iam_member" "service_extensions_sa" {
  for_each = toset(local.model_armor_sa_roles)
  project  = var.project_id
  role     = each.value
  member   = local.service_extensions_sa_member
}

