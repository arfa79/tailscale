"""
Shared pytest configuration and fixtures for the test suite.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def temp_shells_dir():
    """Create a temporary shells directory with test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        shells_path = Path(temp_dir) / "shells"
        shells_path.mkdir()
        
        # Create mock setup script
        setup_script_content = """#!/bin/bash
# Mock Tailscale setup script for testing
set -euo pipefail

echo "Installing Tailscale..."
apt-get update -y
apt-get install -y curl

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

echo "Setting up exit node..."
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf
sysctl -p

tailscale up --authkey="${TS_AUTHKEY}" --advertise-exit-node
echo "Setup completed successfully!"
"""
        setup_script_path = shells_path / "tailscale-exit-node-setup.bash"
        setup_script_path.write_text(setup_script_content)
        
        # Create mock cloud-init wrapper script
        wrapper_script_content = """#!/bin/bash
# Cloud-Init Wrapper Script for Tailscale Exit Node Setup
set -euo pipefail
exec > >(tee -a /var/log/cloud-init-output.log) 2>&1

echo "Starting Tailscale exit node cloud-init setup..."

# Set environment variables for the setup script
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
"""
        wrapper_script_path = shells_path / "cloud-init-wrapper.bash"
        wrapper_script_path.write_text(wrapper_script_content)
        
        yield shells_path


@pytest.fixture
def mock_external_dependencies():
    """Mock external dependencies to prevent actual API calls during testing."""
    with patch.dict('sys.modules', {
        'digitalocean': None,
        'requests': None, 
        'tenacity': None,
        'dotenv': None
    }):
        yield


@pytest.fixture
def sample_config():
    """Provide sample configuration for testing."""
    return {
        'do_token': 'test_do_token_123',
        'ts_authkey': 'test_ts_authkey_456',
        'login_server': 'https://test.tailscale.com',
        'region': 'fra1',
        'image_name': 'ubuntu-22-04',
        'name_prefix': 'test-tailscale-exit',
        'target_nodes': 1,
        'max_nodes': 3,
        'health_check_interval': 60,
        'log_level': 'DEBUG'
    }


# Test markers
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
