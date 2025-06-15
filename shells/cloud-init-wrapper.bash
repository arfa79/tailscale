#!/bin/bash
# Cloud-Init Wrapper Script for Tailscale Exit Node Setup
# This script is used by cloud-init to set up environment and execute the main setup script

set -euo pipefail
exec > >(tee -a /var/log/cloud-init-output.log) 2>&1

echo "Starting Tailscale exit node cloud-init setup..."

# Set environment variables for the setup script
# These will be replaced by the Python script with actual values
export TS_AUTHKEY="{ts_authkey}"
export LOGIN_SERVER="{login_server}"

# Create the setup script
cat > /tmp/tailscale-setup.sh << 'SETUP_SCRIPT_EOF'
{setup_script_content}
SETUP_SCRIPT_EOF

# Make it executable and run it
chmod +x /tmp/tailscale-setup.sh
/tmp/tailscale-setup.sh

# Clean up
rm -f /tmp/tailscale-setup.sh

echo "Cloud-init setup completed!"
