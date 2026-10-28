output "request_template_id" {
  value = var.enable_model_armor ? var.request_template_id : null
}

output "response_template_id" {
  value = var.enable_model_armor ? var.response_template_id : null
}

output "service_extensions_sa_email" {
  value       = var.enable_model_armor ? local.service_extensions_sa_email : null
  description = "Email of the Google-managed Service Extensions service agent (gcp-sa-dep)."
}

output "vertex_ai_sa_email" {
  value       = var.enable_model_armor && var.enable_vertex_ai_integration ? "service-${data.google_project.project.number}@gcp-sa-aiplatform.iam.gserviceaccount.com" : null
  description = "Email of the Google-managed AI Platform service agent."
}
