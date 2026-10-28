# Root Terraform Orchestrator

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID."
  default     = "project-id-change-me"
}

variable "project_number" {
  type        = string
  description = "The Google Cloud Project Number."
  default     = "500797570986"
}

variable "region" {
  type        = string
  description = "The Google Cloud Region."
  default     = "us-central1"
}

module "networking" {
  source                  = "./networking"
  region                  = var.region
  vpc_network_name        = var.vpc_network_name
  subnet_name             = var.subnet_name
  network_attachment_name = var.network_attachment_name
}

variable "vpc_network_name" {
  type        = string
  description = "The name of the VPC network."
  default     = "governed-agent-vpc"
}

variable "subnet_name" {
  type        = string
  description = "The name of the private subnet."
  default     = "agent-private-subnet"
}

variable "network_attachment_name" {
  type        = string
  description = "The name of the PSC network attachment."
  default     = "gateway-egress-na"
}

module "registry" {
  source          = "./registry"
  region          = var.region
  project_id      = var.project_id
  project_number  = var.project_number
  organization_id = var.organization_id
}

module "model_armor" {
  source                           = "./model-armor"
  project_id                       = var.project_id
  region                           = var.region
  enable_model_armor               = var.enable_model_armor
  request_template_id              = var.model_armor_request_template_id
  response_template_id             = var.model_armor_response_template_id
  inspect_template_id              = var.model_armor_inspect_template_id
  deidentify_template_id           = var.model_armor_deidentify_template_id
  enable_vertex_ai_integration     = var.enable_vertex_ai_integration
  vertex_ai_inspect_only           = var.vertex_ai_inspect_only
}

module "gateway" {
  source                                 = "./gateway"
  region                                 = var.region
  project_number                         = var.project_number
  project_id                             = var.project_id
  enable_iap_enforcement                 = var.enable_iap_enforcement
  agent_gateway_name                     = var.agent_gateway_name
  private_subnet_id                      = module.networking.private_subnet_id
  enable_model_armor                     = var.enable_model_armor
  model_armor_request_template_id        = module.model_armor.request_template_id
  model_armor_response_template_id       = module.model_armor.response_template_id
}

variable "agent_gateway_name" {
  type        = string
  description = "The name of the Agent Gateway."
  default     = "gateway-egress"
}

variable "enable_iap_enforcement" {
  type        = bool
  description = "If true, active authorization policies are enforced on the gateway (otherwise runs in DRY_RUN mode)."
  default     = false
}


variable "organization_id" {
  type        = string
  description = "The Google Cloud Organization ID."
}

variable "artifact_registry_repo" {
  type        = string
  description = "The name of the Artifact Registry repository."
  default     = "agent-repo"
}

variable "enable_model_armor" {
  type        = bool
  default     = false
  description = "Whether to enable Model Armor content sanitization on the Agent Gateway."
}

variable "model_armor_request_template_id" {
  type        = string
  default     = null
  description = "The Model Armor template ID for scanning incoming requests."
}

variable "model_armor_response_template_id" {
  type        = string
  default     = null
  description = "The Model Armor template ID for scanning outgoing responses."
}

variable "model_armor_inspect_template_id" {
  type        = string
  default     = null
  description = "The DLP inspect template ID used by Model Armor."
}

variable "model_armor_deidentify_template_id" {
  type        = string
  default     = null
  description = "The DLP de-identify template ID used by Model Armor."
}

variable "enable_vertex_ai_integration" {
  type        = bool
  default     = true
  description = "Whether to enable Model Armor integrated service protections for Vertex AI."
}

variable "vertex_ai_inspect_only" {
  type        = bool
  default     = false
  description = "Whether Vertex AI Model Armor floor setting should be inspect-only (if false, inspect_and_block is enabled)."
}

resource "google_artifact_registry_repository" "agent_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repo
  format        = "DOCKER"
  description   = "Docker repository for agents and tools"
}

# Grant roles/compute.networkAdmin to Vertex AI Service Agent
resource "google_project_iam_member" "aiplatform_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Grant roles/compute.networkAdmin to Vertex AI Reasoning Engine Service Agent
resource "google_project_iam_member" "aiplatform_re_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

# Grant roles/agentregistry.viewer to the agent workload identity principal set
resource "google_project_iam_member" "agent_identity_agentregistry_viewer" {
  project = var.project_id
  role    = "roles/agentregistry.viewer"
  member  = "principalSet://agents.global.org-${var.organization_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/${var.project_number}"
}

# Grant roles/browser to the agent workload identity principal set (Primary Source of Truth)
# Required for Vertex AI SDK container init to call resourcemanager.projects.get
resource "google_project_iam_member" "agent_identity_browser" {
  project = var.project_id
  role    = "roles/browser"
  member  = "principalSet://agents.global.org-${var.organization_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/${var.project_number}"
}

# Grant roles/iam.serviceAccountTokenCreator to Vertex AI Reasoning Engine Service Agent
# This is required for the Reasoning Engine runtime to generate OIDC identity tokens to call MCP tools on Cloud Run.
resource "google_project_iam_member" "aiplatform_re_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

output "model_armor_service_extensions_sa_email" {
  value       = module.model_armor.service_extensions_sa_email
  description = "Email of the Google-managed Service Extensions service agent (gcp-sa-dep)."
}

output "model_armor_vertex_ai_sa_email" {
  value       = module.model_armor.vertex_ai_sa_email
  description = "Email of the Google-managed AI Platform service agent."
}






