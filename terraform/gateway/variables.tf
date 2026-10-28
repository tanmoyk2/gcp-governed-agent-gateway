variable "region" {
  type        = string
  description = "The Google Cloud region where the gateway will be deployed."
}

variable "project_number" {
  type        = string
  description = "The Google Cloud project number."
}

variable "project_id" {
  type        = string
  description = "The Google Cloud project ID."
}

variable "gateway_psc_ip" {
  type        = string
  description = "The IP address reserved for the Private Service Connect gateway."
  default     = ""
}

variable "enable_iap_enforcement" {
  type        = bool
  description = "If true, active authorization policies are enforced on the gateway."
}

variable "agent_gateway_name" {
  type        = string
  description = "The name of the Agent Gateway."
}

variable "private_subnet_id" {
  type        = string
  description = "The ID of the private subnet to connect the Agent Gateway to."
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

