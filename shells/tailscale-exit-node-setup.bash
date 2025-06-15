#!/bin/bash
# Tailscale Exit Node Setup Script
# This script is executed via cloud-init to set up a Tailscale exit node

set -euo pipefail
exec > >(tee -a /var/log/tailscale-setup.log) 2>&1

# Configuration from environment variables
TS_AUTHKEY="${TS_AUTHKEY:-}"
LOGIN_SERVER="${LOGIN_SERVER:-https://controlplane.tailscale.com}"

echo "Starting Tailscale exit node setup..."
echo "Timestamp: $(date)"
echo "Login server: ${LOGIN_SERVER}"

# Validate required variables
if [[ -z "${TS_AUTHKEY}" ]]; then
    echo "ERROR: TS_AUTHKEY environment variable is required"
    exit 1
fi

# Update system packages
echo "Updating system packages..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
apt-get install -y curl python3 wget gnupg lsb-release

# Install Tailscale
echo "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

# Configure IP forwarding for exit node functionality
echo "Configuring IP forwarding..."
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf
echo 'net.ipv6.conf.all.forwarding = 1' >> /etc/sysctl.conf
sysctl -p

# Start Tailscale and authenticate as exit node
echo "Starting Tailscale and authenticating..."
tailscale up \
    --authkey="${TS_AUTHKEY}" \
    --advertise-exit-node \
    --login-server="${LOGIN_SERVER}" \
    --accept-routes \
    --timeout=300s

# Wait for Tailscale to be ready
echo "Waiting for Tailscale to be ready..."
sleep 15

# Verify Tailscale is running
if ! tailscale status > /dev/null 2>&1; then
    echo "ERROR: Tailscale failed to start properly"
    exit 1
fi

# Create status files directory
echo "Setting up status monitoring..."
mkdir -p /var/www/html

# Create status update script
cat > /usr/local/bin/update-tailscale-status.sh << 'EOF'
#!/bin/bash
# Update Tailscale status files for HTTP monitoring

set -e

STATUS_DIR="/var/www/html"
mkdir -p "${STATUS_DIR}"

# Get Tailscale status (JSON format)
if tailscale status --json > "${STATUS_DIR}/tailscale-status.json" 2>/dev/null; then
    echo "Status updated: $(date)" >> "${STATUS_DIR}/last-update.txt"
else
    echo '{"error": "tailscale status command failed"}' > "${STATUS_DIR}/tailscale-status.json"
fi

# Get Tailscale IPv4 address
if tailscale ip --4 > "${STATUS_DIR}/tailscale-ip.txt" 2>/dev/null; then
    echo "IP updated: $(date)" >> "${STATUS_DIR}/last-update.txt"
else
    echo 'N/A' > "${STATUS_DIR}/tailscale-ip.txt"
fi

# Create ready indicator
echo "ready" > "${STATUS_DIR}/setup-complete"
echo "$(date): Status files updated" >> "${STATUS_DIR}/last-update.txt"
EOF

chmod +x /usr/local/bin/update-tailscale-status.sh

# Create systemd service for status updates
echo "Creating systemd services..."
cat > /etc/systemd/system/tailscale-status.service << 'EOF'
[Unit]
Description=Tailscale Status Updater
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/update-tailscale-status.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create systemd timer for regular status updates
cat > /etc/systemd/system/tailscale-status.timer << 'EOF'
[Unit]
Description=Update Tailscale Status Every 30 Seconds
Requires=tailscale-status.service

[Timer]
OnBootSec=30sec
OnUnitActiveSec=30sec
AccuracySec=5sec

[Install]
WantedBy=timers.target
EOF

# Create HTTP server service for status endpoint
cat > /etc/systemd/system/tailscale-status-server.service << 'EOF'
[Unit]
Description=Tailscale Status HTTP Server
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/html
ExecStart=/usr/bin/python3 -m http.server 8080
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/www/html

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable services
echo "Enabling and starting services..."
systemctl daemon-reload
systemctl enable tailscale-status.timer tailscale-status-server.service
systemctl start tailscale-status.timer tailscale-status-server.service

# Run initial status update
echo "Running initial status update..."
/usr/local/bin/update-tailscale-status.sh

# Verify everything is working
echo "Verifying setup..."
sleep 5

if systemctl is-active --quiet tailscale-status-server.service; then
    echo "✓ Status server is running"
else
    echo "⚠ Status server is not running"
    systemctl status tailscale-status-server.service
fi

if systemctl is-active --quiet tailscale-status.timer; then
    echo "✓ Status timer is running"
else
    echo "⚠ Status timer is not running"
    systemctl status tailscale-status.timer
fi

# Display Tailscale status
echo "Tailscale status:"
tailscale status || echo "Failed to get Tailscale status"

echo "Tailscale exit node setup completed successfully!"
echo "Setup completed at: $(date)"
echo "Status endpoint available at: http://$(hostname -I | awk '{print $1}'):8080/"
