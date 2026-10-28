# Shared Registry Module
# This module enables the agentregistry.googleapis.com service API
# and initializes the regional registry namespace.

variable "region" {
  type        = string
  description = "The Google Cloud region for the Agent Registry."
}

variable "project_id" {
  type        = string
  description = "The Google Cloud project ID."
}

variable "project_number" {
  type        = string
  description = "The Google Cloud project number."
}

variable "organization_id" {
  type        = string
  description = "The Google Cloud Organization ID."
}

variable "google_apis" {
  type        = map(string)
  description = "List of Google APIs to register in the Agent Registry with all permutations."
  default     = {
    "aiplatform"            = "Vertex AI API"
    "cloudresourcemanager"  = "Cloud Resource Manager API"
    "logging"               = "Cloud Logging API"
    "monitoring"            = "Cloud Monitoring API"
    "oauth2"                = "Google OAuth2 API"
    "agentregistry"         = "Agent Registry API"
    "iap-api"               = "Identity-Aware Proxy API"
    "iamcredentials"        = "IAM Credentials API"
    "telemetry"             = "Google Telemetry API"
    "trace"                 = "Google Cloud Trace API"
  }
}

# Enable the Agent Registry API
resource "google_project_service" "agent_registry_api" {
  project                    = var.project_id
  service                    = "agentregistry.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Grant IAP egressor permissions on the regional Agent Registry to the Reasoning Engines (Step 1)
resource "null_resource" "agent_registry_egressor_binding" {
  provisioner "local-exec" {
    command = "gcloud beta iap web add-iam-policy-binding --resource-type=agent-registry --region=${var.region} --member='principalSet://agents.global.org-${var.organization_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/${var.project_number}' --role='roles/iap.egressor' --project=${var.project_id} --quiet"
  }

  depends_on = [google_project_service.agent_registry_api]
}

# Grant IAP egressor permissions on the regional Agent Registry to the Compute Service Account (Step 2)
# Serialized via depends_on to prevent concurrent IAM setIamPolicy conflicts.
resource "null_resource" "compute_sa_egressor_binding" {
  provisioner "local-exec" {
    command = "gcloud beta iap web add-iam-policy-binding --resource-type=agent-registry --region=${var.region} --member='serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com' --role='roles/iap.egressor' --project=${var.project_id} --quiet"
  }

  depends_on = [null_resource.agent_registry_egressor_binding]
}

# Grant IAP egressor permissions on the regional Agent Registry to the Vertex AI RE Service Agent (Step 3)
# Serialized via depends_on to prevent concurrent IAM setIamPolicy conflicts.
resource "null_resource" "aiplatform_sa_egressor_binding" {
  provisioner "local-exec" {
    command = "gcloud beta iap web add-iam-policy-binding --resource-type=agent-registry --region=${var.region} --member='serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com' --role='roles/iap.egressor' --project=${var.project_id} --quiet"
  }

  depends_on = [null_resource.compute_sa_egressor_binding]
}

# Register core Google APIs in Agent Registry dynamically
resource "null_resource" "register_google_apis" {
  triggers = {
    google_apis = jsonencode(var.google_apis)
    project_id  = var.project_id
    region      = var.region
  }

  provisioner "local-exec" {
    command = templatefile("${path.module}/scripts/register_endpoints.sh.tpl", {
      google_apis = var.google_apis
    })

    environment = {
      PROJECT_ID = var.project_id
      LOCATION   = var.region
    }
  }

  depends_on = [google_project_service.agent_registry_api]
}
