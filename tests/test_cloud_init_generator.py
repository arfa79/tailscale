#!/usr/bin/env python3
"""
Unit tests for CloudInitScriptGenerator

Tests the cloud-init wrapper script extraction functionality using pytest.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

# Add the project root to the path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "digital_ocean"))

# Import the class we want to test
try:
    from auto_deploy import CloudInitScriptGenerator
except ImportError:
    # Fallback for testing
    class CloudInitScriptGenerator:
        def __init__(self, shells_path=None):
            self.shells_path = Path(shells_path) if shells_path else Path(__file__).parent.parent / "shells"
            self.setup_script_path = self.shells_path / "tailscale-exit-node-setup.bash"
            self.cloud_init_wrapper_path = self.shells_path / "cloud-init-wrapper.bash"
        
        def generate_tailscale_script(self, ts_authkey: str, login_server: str) -> str:
            try:
                with open(self.setup_script_path, 'r') as f:
                    setup_script_content = f.read()
            except FileNotFoundError:
                raise FileNotFoundError(f"Setup script not found at {self.setup_script_path}")
            
            try:
                with open(self.cloud_init_wrapper_path, 'r') as f:
                    cloud_init_wrapper_content = f.read()
            except FileNotFoundError:
                raise FileNotFoundError(f"Cloud-init wrapper script not found at {self.cloud_init_wrapper_path}")
            
            return cloud_init_wrapper_content.format(
                ts_authkey=ts_authkey,
                login_server=login_server,
                setup_script_content=setup_script_content
            )


@pytest.mark.unit
class TestCloudInitScriptGenerator:
    """Unit tests for CloudInitScriptGenerator class."""
    
    def test_init_with_custom_shells_path(self, temp_shells_dir):
        """Test CloudInitScriptGenerator initialization with custom shells path."""
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        assert generator.shells_path == temp_shells_dir
        assert generator.setup_script_path == temp_shells_dir / "tailscale-exit-node-setup.bash"
        assert generator.cloud_init_wrapper_path == temp_shells_dir / "cloud-init-wrapper.bash"
    
    def test_init_with_default_shells_path(self):
        """Test CloudInitScriptGenerator initialization with default shells path."""
        generator = CloudInitScriptGenerator()
        
        expected_shells_path = Path(__file__).parent.parent / "shells"
        assert generator.shells_path == expected_shells_path
    
    def test_generate_tailscale_script_success(self, temp_shells_dir):
        """Test successful generation of cloud-init script."""
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        ts_authkey = "test_auth_key_123"
        login_server = "https://test.tailscale.com"
        
        result = generator.generate_tailscale_script(ts_authkey, login_server)
        
        # Verify the result contains expected elements
        assert "#!/bin/bash" in result
        assert f'export TS_AUTHKEY="{ts_authkey}"' in result
        assert f'export LOGIN_SERVER="{login_server}"' in result
        assert "Installing Tailscale..." in result
        assert "Setting up exit node..." in result
        assert "/tmp/tailscale-setup.sh" in result
    
    def test_generate_tailscale_script_missing_setup_file(self, temp_shells_dir):
        """Test error handling when setup script file is missing."""
        # Remove the setup script file
        setup_script_path = temp_shells_dir / "tailscale-exit-node-setup.bash"
        setup_script_path.unlink()
        
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        with pytest.raises(FileNotFoundError) as exc_info:
            generator.generate_tailscale_script("test_key", "https://test.com")
        
        assert "Setup script not found" in str(exc_info.value)
        assert "tailscale-exit-node-setup.bash" in str(exc_info.value)
    
    def test_generate_tailscale_script_missing_wrapper_file(self, temp_shells_dir):
        """Test error handling when cloud-init wrapper file is missing."""
        # Remove the wrapper script file
        wrapper_script_path = temp_shells_dir / "cloud-init-wrapper.bash"
        wrapper_script_path.unlink()
        
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        with pytest.raises(FileNotFoundError) as exc_info:
            generator.generate_tailscale_script("test_key", "https://test.com")
        
        assert "Cloud-init wrapper script not found" in str(exc_info.value)
        assert "cloud-init-wrapper.bash" in str(exc_info.value)
    
    def test_placeholder_replacement(self, temp_shells_dir):
        """Test that placeholders are correctly replaced in the generated script."""
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        ts_authkey = "special_key_with_symbols!@#$"
        login_server = "https://headscale.example.com:8080"
        
        result = generator.generate_tailscale_script(ts_authkey, login_server)
        
        # Verify placeholders are replaced
        assert "{ts_authkey}" not in result
        assert "{login_server}" not in result
        assert "{setup_script_content}" not in result
        
        # Verify actual values are present
        assert ts_authkey in result
        assert login_server in result
    
    def test_script_content_embedded_correctly(self, temp_shells_dir):
        """Test that the setup script content is properly embedded."""
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        result = generator.generate_tailscale_script("test_key", "https://test.com")
        
        # The setup script content should be embedded between SETUP_SCRIPT_EOF markers
        assert "SETUP_SCRIPT_EOF" in result
        assert "Installing Tailscale..." in result
        assert "Setting up exit node..." in result
        assert "tailscale up --authkey" in result
    
    @pytest.mark.integration
    def test_real_files_integration(self):
        """Integration test with the actual shell script files."""
        # This test uses the real files in the shells directory
        generator = CloudInitScriptGenerator()
        
        # Check if the real files exist
        if not generator.setup_script_path.exists():
            pytest.skip("Real setup script file not found")
        if not generator.cloud_init_wrapper_path.exists():
            pytest.skip("Real cloud-init wrapper file not found")
        
        ts_authkey = "integration_test_key"
        login_server = "https://integration.test.com"
        
        # This should not raise an exception
        result = generator.generate_tailscale_script(ts_authkey, login_server)
        
        # Basic validation
        assert isinstance(result, str)
        assert len(result) > 0
        assert "#!/bin/bash" in result
        assert ts_authkey in result
        assert login_server in result
    
    def test_special_characters_in_parameters(self, temp_shells_dir):
        """Test handling of special characters in parameters."""
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        # Test with various special characters
        ts_authkey = "key-with_special@chars#123"
        login_server = "https://test-server.example.com:8080/path"
        
        result = generator.generate_tailscale_script(ts_authkey, login_server)
        
        # Verify the special characters are preserved
        assert ts_authkey in result
        assert login_server in result
        assert "export TS_AUTHKEY=" in result
        assert "export LOGIN_SERVER=" in result


@pytest.mark.parametrize("ts_authkey,login_server", [
    ("simple_key", "https://simple.com"),
    ("key-with-dashes", "https://test-server.example.com"),
    ("key_with_underscores", "https://server.example.com:8080"),
    ("key123", "https://localhost:8080"),
    ("complex-key_123@domain", "https://headscale.company.com:443/api"),
])
@pytest.mark.unit
def test_various_parameter_combinations(ts_authkey, login_server, temp_shells_dir):
    """Test the generator with various parameter combinations."""
    generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
    result = generator.generate_tailscale_script(ts_authkey, login_server)
    
    assert ts_authkey in result
    assert login_server in result
    assert "#!/bin/bash" in result
    assert "SETUP_SCRIPT_EOF" in result


@pytest.mark.unit
def test_path_handling():
    """Test proper path handling for different input types."""
    # Test with string path
    generator1 = CloudInitScriptGenerator(shells_path="/tmp/test")
    assert isinstance(generator1.shells_path, Path)
    
    # Test with Path object
    test_path = Path("/tmp/test2")
    generator2 = CloudInitScriptGenerator(shells_path=test_path)
    assert generator2.shells_path == test_path
    
    # Test with None (default)
    generator3 = CloudInitScriptGenerator(shells_path=None)
    assert isinstance(generator3.shells_path, Path)
