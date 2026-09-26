variable "region" {
  type    = string
  default = "ap-south-1"
}

# c6i.2xlarge (8 vCPU / 16 GB, paid from credits). Free-tier fallback: m7i-flex.large (2 vCPU / 8 GB).
variable "instance_type" {
  type    = string
  default = "c6i.2xlarge"
}

# SSH is allowed only from this range, e.g. "203.0.113.7/32" (your public IP).
variable "ssh_cidr" {
  type = string
}

variable "disk_gb" {
  type    = number
  default = 30
}

variable "public_key_path" {
  type    = string
  default = "~/.ssh/adlyser.pub"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/Phantom-VK/ADlyser.git"
}
