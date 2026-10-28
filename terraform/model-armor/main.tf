data "google_project" "project" {
  project_id = var.project_id
}

locals {
  # Service Extensions service account format: service-PROJECT_NUMBER@gcp-sa-dep.iam.gserviceaccount.com
  # This account is automatically created when networkservices.googleapis.com is enabled
  # See: https://cloud.google.com/service-extensions/docs/configure-extensions-to-google-services
  service_extensions_sa_email = "service-${data.google_project.project.number}@gcp-sa-dep.iam.gserviceaccount.com"
}

# Enable the DLP API
resource "google_project_service" "dlp" {
  count                      = var.enable_model_armor ? 1 : 0
  project                    = var.project_id
  service                    = "dlp.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Enable the Model Armor API
resource "google_project_service" "model_armor" {
  count                      = var.enable_model_armor ? 1 : 0
  project                    = var.project_id
  service                    = "modelarmor.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# 1. DLP Inspect Template (Advanced SDP)
resource "google_data_loss_prevention_inspect_template" "ssn" {
  count        = var.enable_model_armor ? 1 : 0
  parent       = "projects/${var.project_id}/locations/${var.region}"
  template_id  = var.inspect_template_id
  display_name = "SSN Inspect Template"

  inspect_config {
    dynamic "info_types" {
      for_each = var.pii_types
      content {
        name = info_types.value
      }
    }
    min_likelihood = "POSSIBLE"
  }

  depends_on = [google_project_service.dlp]
}

# 2. DLP De-identify Template (Advanced SDP)
resource "google_data_loss_prevention_deidentify_template" "ssn" {
  count        = var.enable_model_armor ? 1 : 0
  parent       = "projects/${var.project_id}/locations/${var.region}"
  template_id  = var.deidentify_template_id
  display_name = "SSN Redaction Template"

  deidentify_config {
    info_type_transformations {
      transformations {
        dynamic "info_types" {
          for_each = var.pii_types
          content {
            name = info_types.value
          }
        }
        primitive_transformation {
          replace_with_info_type_config = true
        }
      }
    }
  }

  depends_on = [google_project_service.dlp]
}

# 3. Model Armor Service Agent IAM
resource "google_project_service_identity" "model_armor" {
  count    = var.enable_model_armor ? 1 : 0
  provider = google-beta
  project  = var.project_id
  service  = "modelarmor.googleapis.com"

  depends_on = [google_project_service.model_armor]
}

resource "google_project_iam_member" "model_armor_dlp_user" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/dlp.user"
  member  = "serviceAccount:${google_project_service_identity.model_armor[0].email}"
}

resource "google_project_iam_member" "model_armor_dlp_reader" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/dlp.reader"
  member  = "serviceAccount:${google_project_service_identity.model_armor[0].email}"
}

# =============================================================================
# IAM Bindings for Service Extensions Service Account (gcp-sa-dep)
# Required for GCPTrafficExtension / Agent Gateway to call Model Armor
# See: https://cloud.google.com/service-extensions/docs/configure-extensions-to-google-services
# =============================================================================

# Grant container.admin role for GKE/Gateway access (required by Service Extensions)
resource "google_project_iam_member" "service_extensions_container_admin" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/container.admin"
  member  = "serviceAccount:${local.service_extensions_sa_email}"
}

# Grant modelarmor.calloutUser role for Model Armor callouts
resource "google_project_iam_member" "service_extensions_callout_user" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/modelarmor.calloutUser"
  member  = "serviceAccount:${local.service_extensions_sa_email}"
}

# Grant serviceusage.serviceUsageConsumer role for API usage
resource "google_project_iam_member" "service_extensions_service_usage" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${local.service_extensions_sa_email}"
}

# Grant modelarmor.user role for Model Armor usage
resource "google_project_iam_member" "service_extensions_model_armor_user" {
  count   = var.enable_model_armor ? 1 : 0
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:${local.service_extensions_sa_email}"
}

# =============================================================================
# Model Armor Floor Setting for Vertex AI Protection
# Configures project-level floor setting with AI_PLATFORM as integrated service
# =============================================================================

resource "google_model_armor_floorsetting" "vertex_ai_floor_setting" {
  count    = var.enable_model_armor && var.enable_vertex_ai_integration ? 1 : 0
  parent   = "projects/${var.project_id}"
  location = "global"

  enable_floor_setting_enforcement = true

  integrated_services = ["AI_PLATFORM"]

  filter_config {
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
  }

  dynamic "ai_platform_floor_setting" {
    for_each = var.vertex_ai_inspect_only ? [1] : []
    content {
      inspect_only         = true
      enable_cloud_logging = true
    }
  }

  dynamic "ai_platform_floor_setting" {
    for_each = !var.vertex_ai_inspect_only ? [1] : []
    content {
      inspect_and_block    = true
      enable_cloud_logging = true
    }
  }

  depends_on = [google_project_service.model_armor]
}

# =============================================================================
# Vertex AI Service Agent IAM Binding
# Grants roles/modelarmor.user to the AI Platform service agent so Vertex AI
# can invoke Model Armor sanitization
# =============================================================================

resource "google_project_iam_member" "vertex_ai_model_armor_user" {
  count   = var.enable_model_armor && var.enable_vertex_ai_integration ? 1 : 0
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# 4. Model Armor Request Template
resource "google_model_armor_template" "request" {
  count       = var.enable_model_armor ? 1 : 0
  project     = var.project_id
  location    = var.region
  template_id = var.request_template_id

  filter_config {
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }

    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }

    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }

    sdp_settings {
      advanced_config {
        inspect_template    = google_data_loss_prevention_inspect_template.ssn[0].id
        deidentify_template = google_data_loss_prevention_deidentify_template.ssn[0].id
      }
    }
  }

  template_metadata {
    custom_prompt_safety_error_code    = 799
    custom_prompt_safety_error_message = "Your request was blocked by our content filter. Please rephrase and try again."
    ignore_partial_invocation_failures = true
    log_template_operations            = true
    log_sanitize_operations            = true
  }

  depends_on = [
    google_project_service.model_armor,
    google_project_service.dlp,
    google_data_loss_prevention_inspect_template.ssn,
    google_data_loss_prevention_deidentify_template.ssn,
    google_model_armor_floorsetting.vertex_ai_floor_setting,
  ]
}

# 5. Model Armor Response Template
resource "google_model_armor_template" "response" {
  count       = var.enable_model_armor ? 1 : 0
  project     = var.project_id
  location    = var.region
  template_id = var.response_template_id

  depends_on = [
    google_project_service.model_armor,
    google_project_service.dlp,
    google_data_loss_prevention_inspect_template.ssn,
    google_data_loss_prevention_deidentify_template.ssn,
    google_model_armor_floorsetting.vertex_ai_floor_setting,
  ]


  filter_config {
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }

    sdp_settings {
      advanced_config {
        inspect_template    = google_data_loss_prevention_inspect_template.ssn[0].id
        deidentify_template = google_data_loss_prevention_deidentify_template.ssn[0].id
      }
    }

    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }

    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
  }

  template_metadata {
    custom_llm_response_safety_error_code    = 798
    custom_llm_response_safety_error_message = "LLM response blocked by content filter"
    ignore_partial_invocation_failures       = true
    log_sanitize_operations                  = true
    log_template_operations                  = true
  }
}
