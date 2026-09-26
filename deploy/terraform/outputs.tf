output "public_ip" {
  value = aws_eip.adlyser.public_ip
}

output "url" {
  value = "https://${local.hostname}"
}

output "ssh" {
  value = "ssh -i ~/.ssh/adlyser ubuntu@${aws_eip.adlyser.public_ip}"
}
