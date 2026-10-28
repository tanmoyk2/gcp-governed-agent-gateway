variable "region" {
  type        = string
  description = "The Google Cloud region where resources will be provisioned."
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

