terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

# Latest Ubuntu 24.04 LTS (Canonical).
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_key_pair" "adlyser" {
  key_name   = "adlyser"
  public_key = file(pathexpand(var.public_key_path))
}

resource "aws_security_group" "adlyser" {
  name        = "adlyser"
  description = "ADlyser demo: web open, SSH from one IP"

  ingress {
    description = "HTTP (Caddy redirects to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Allocated before the instance so the sslip.io hostname can go into the bootstrap script.
resource "aws_eip" "adlyser" {
  domain = "vpc"
  tags   = { Name = "adlyser" }
}

locals {
  hostname = "${replace(aws_eip.adlyser.public_ip, ".", "-")}.sslip.io"
}

resource "aws_instance" "adlyser" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.adlyser.key_name
  vpc_security_group_ids = [aws_security_group.adlyser.id]

  root_block_device {
    volume_size = var.disk_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/bootstrap.sh.tftpl", {
    hostname = local.hostname
    repo_url = var.repo_url
  })

  tags = { Name = "adlyser" }
}

resource "aws_eip_association" "adlyser" {
  instance_id   = aws_instance.adlyser.id
  allocation_id = aws_eip.adlyser.id
}
