# Deploy (EC2 + Caddy, no Docker)

Creates one Ubuntu 24.04 instance in ap-south-1 with an Elastic IP, a security group
(80/443 open, 22 from your IP only) and HTTPS on `<ip>.sslip.io`.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/adlyser -N ""     # once, if the key doesn't exist
cd deploy/terraform
terraform init
terraform apply -var "ssh_cidr=$(curl -s https://ifconfig.me)/32"
# free tier: add -var instance_type=m7i-flex.large
```

Wait for first-boot setup (about 3 minutes), then finish over SSH:

```bash
IP=$(terraform output -raw public_ip)
ssh -i ~/.ssh/adlyser ubuntu@$IP 'test -f /var/log/adlyser-bootstrap.done && echo ready'

# From the repo root on your machine:
rsync -avz -e "ssh -i ~/.ssh/adlyser" <local videos dir>/ ubuntu@$IP:/srv/videos/
rsync -avz -e "ssh -i ~/.ssh/adlyser" --exclude uploads --exclude 'cache.*' --exclude '*.log' data/ ubuntu@$IP:ADlyser/data/
scp -i ~/.ssh/adlyser .env ubuntu@$IP:ADlyser/.env

ssh -i ~/.ssh/adlyser ubuntu@$IP
  chmod 600 ~/ADlyser/.env
  cd ~/ADlyser && ~/.local/bin/uv sync
  ~/.local/bin/uv run hf download BAAI/bge-m3
  cd web && npm ci && npm run build
  sudo systemctl enable --now adlyser
```

Open `terraform output -raw url`. Tear down with `terraform destroy`.
