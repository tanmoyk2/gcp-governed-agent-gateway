# Core Egress Networking Module
# This file declares the private VPC network, the private subnets, and the regional
# Private Service Connect (PSC) network attachment to establish the network boundaries.

resource "google_compute_network" "vpc" {
  name                    = var.vpc_network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private_subnet" {
  name          = var.subnet_name
  ip_cidr_range = "10.128.0.0/20"
  network       = google_compute_network.vpc.id
  region        = var.region
}

resource "google_compute_network_attachment" "gateway_egress_na" {
  name                  = var.network_attachment_name
  region                = var.region
  connection_preference = "ACCEPT_AUTOMATIC"
  subnetworks           = [google_compute_subnetwork.private_subnet.id]
}

