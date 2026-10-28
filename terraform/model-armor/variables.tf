variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID."
}

variable "region" {
  type        = string
  description = "The region for resource deployment."
}

variable "enable_model_armor" {
  type        = bool
  default     = true
  description = "Whether to enable Model Armor template creation."
}

variable "request_template_id" {
  type        = string
  description = "ID for the request-side Model Armor template."
}

variable "response_template_id" {
  type        = string
  description = "ID for the response-side Model Armor template."
}

variable "inspect_template_id" {
  type        = string
  description = "ID for the DLP inspect template."
}

variable "deidentify_template_id" {
  type        = string
  description = "ID for the DLP de-identify template."
}

variable "pii_types" {
  type        = list(string)
  default     = ["US_SOCIAL_SECURITY_NUMBER", "CREDIT_CARD_NUMBER", "PHONE_NUMBER", "EMAIL_ADDRESS"]
  description = "PII types to detect and redact."
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
