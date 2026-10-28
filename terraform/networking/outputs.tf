output "vpc_id" {
  value       = google_compute_network.vpc.id
  description = "The ID of the created private VPC network."
}

output "private_subnet_id" {
  value       = google_compute_subnetwork.private_subnet.id
  description = "The ID of the private subnet."
}

output "gateway_egress_na_id" {
  value       = google_compute_network_attachment.gateway_egress_na.id
  description = "The ID of the gateway egress network attachment."
}

