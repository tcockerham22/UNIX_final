output "edge_public_ip" {
  description = "Reserved public address for the Ada edge VM."
  value       = google_compute_address.edge.address
}

output "edge_private_ip" {
  description = "Internal address of the edge VM."
  value       = google_compute_instance.edge.network_interface[0].network_ip
}

output "ai_private_ip" {
  description = "Internal address of the AI VM; the edge VM proxies inference here."
  value       = google_compute_instance.ai.network_interface[0].network_ip
}

output "service_account_email" {
  description = "Least-privilege service account attached to both VMs."
  value       = google_service_account.ada_vm.email
}

output "secret_names" {
  description = "Secret Manager secrets created for the Ada stack."
  value       = sort(keys(google_secret_manager_secret.ada))
}

output "ssh_command" {
  description = "IAP SSH command for the edge VM."
  value       = "gcloud compute ssh ${google_compute_instance.edge.name} --project=${var.project_id} --zone=${var.zone} --tunnel-through-iap"
}

output "chat_url" {
  description = "Public chat URL after startup completes."
  value       = "http://${google_compute_address.edge.address}/"
}
