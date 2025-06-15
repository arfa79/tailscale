#!/usr/bin/env python3
"""
End-to-end integration tests for the Tailscale auto-deployment system.

These tests validate the complete workflow including:
- Script generation
- File system operations
- Configuration handling
- Error scenarios
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.mark.integration
@pytest.mark.slow
class TestEndToEndWorkflow:
    """End-to-end integration tests."""
    
    def test_complete_script_generation_workflow(self, temp_shells_dir):
        """Test the complete script generation workflow."""
        # Import here to avoid dependency issues
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "digital_ocean"))
        
        try:
            from auto_deploy import CloudInitScriptGenerator
        except ImportError:
            pytest.skip("CloudInitScriptGenerator not available")
        
        # Create generator with test shells directory
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        # Test configuration
        ts_authkey = "tskey-1234567890abcdef"
        login_server = "https://headscale.company.com"
        
        # Generate the script
        result = generator.generate_tailscale_script(ts_authkey, login_server)
        
        # Validate the complete generated script
        assert isinstance(result, str)
        assert len(result) > 500  # Should be substantial
        
        # Check for all expected components
        expected_components = [
            "#!/bin/bash",
            "set -euo pipefail",
            "cloud-init-output.log",
            f'export TS_AUTHKEY="{ts_authkey}"',
            f'export LOGIN_SERVER="{login_server}"',
            "SETUP_SCRIPT_EOF",
            "/tmp/tailscale-setup.sh",
            "chmod +x",
            "Installing Tailscale...",
            "Setting up exit node...",
            "tailscale up --authkey",
            "Setup completed successfully!"
        ]
        
        for component in expected_components:
            assert component in result, f"Missing component: {component}"
    
    def test_file_system_integration(self):
        """Test integration with the real file system."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "digital_ocean"))
        
        try:
            from auto_deploy import CloudInitScriptGenerator
        except ImportError:
            pytest.skip("CloudInitScriptGenerator not available")
        
        # Use the real shells directory
        real_shells_path = Path(__file__).parent.parent.parent / "shells"
        
        if not real_shells_path.exists():
            pytest.skip("Real shells directory not found")
        
        generator = CloudInitScriptGenerator()
        
        # Check that files exist
        assert generator.setup_script_path.exists(), "Setup script file missing"
        assert generator.cloud_init_wrapper_path.exists(), "Wrapper script file missing"
        
        # Test script generation with real files
        result = generator.generate_tailscale_script(
            "test_integration_key",
            "https://test.integration.com"
        )
        
        # Basic validation
        assert "#!/bin/bash" in result
        assert "test_integration_key" in result
        assert "https://test.integration.com" in result
    
    def test_error_handling_integration(self, temp_shells_dir):
        """Test error handling in integration scenarios."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "digital_ocean"))
        
        try:
            from auto_deploy import CloudInitScriptGenerator
        except ImportError:
            pytest.skip("CloudInitScriptGenerator not available")
        
        # Test with non-existent directory
        non_existent_path = temp_shells_dir / "non_existent"
        generator = CloudInitScriptGenerator(shells_path=str(non_existent_path))
        
        with pytest.raises(FileNotFoundError):
            generator.generate_tailscale_script("key", "server")
    
    def test_script_content_validation(self, temp_shells_dir):
        """Test that generated scripts contain all necessary components for cloud-init."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "digital_ocean"))
        
        try:
            from auto_deploy import CloudInitScriptGenerator
        except ImportError:
            pytest.skip("CloudInitScriptGenerator not available")
        
        generator = CloudInitScriptGenerator(shells_path=str(temp_shells_dir))
        
        result = generator.generate_tailscale_script(
            "prod-key-123",
            "https://headscale.production.com"
        )
        
        # Validate cloud-init specific requirements
        cloud_init_requirements = [
            "#!/bin/bash",  # Proper shebang
            "set -euo pipefail",  # Error handling
            "tee -a /var/log/cloud-init-output.log",  # Logging
            "export TS_AUTHKEY=",  # Environment variables
            "export LOGIN_SERVER=",
            "chmod +x",  # Executable permissions
            "rm -f",  # Cleanup
        ]
        
        for requirement in cloud_init_requirements:
            assert requirement in result, f"Missing cloud-init requirement: {requirement}"
        
        # Validate Tailscale specific components
        tailscale_requirements = [
            "tailscale up",
            "--authkey",
            "--advertise-exit-node",
            "net.ipv4.ip_forward",
            "sysctl -p",
        ]
        
        for requirement in tailscale_requirements:
            assert requirement in result, f"Missing Tailscale requirement: {requirement}"


@pytest.mark.integration
def test_multiple_script_generations():
    """Test generating multiple scripts to ensure no state pollution."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "digital_ocean"))
    
    try:
        from auto_deploy import CloudInitScriptGenerator
    except ImportError:
        pytest.skip("CloudInitScriptGenerator not available")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        shells_path = Path(temp_dir) / "shells"
        shells_path.mkdir()
        
        # Create test files
        (shells_path / "tailscale-exit-node-setup.bash").write_text("#!/bin/bash\necho 'test setup'")
        (shells_path / "cloud-init-wrapper.bash").write_text(
            "#!/bin/bash\nexport TS_AUTHKEY=\"{ts_authkey}\"\n"
            "export LOGIN_SERVER=\"{login_server}\"\n{setup_script_content}"
        )
        
        generator = CloudInitScriptGenerator(shells_path=str(shells_path))
        
        # Generate multiple scripts with different parameters
        configs = [
            ("key1", "https://server1.com"),
            ("key2", "https://server2.com"), 
            ("key3", "https://server3.com"),
        ]
        
        results = []
        for key, server in configs:
            result = generator.generate_tailscale_script(key, server)
            results.append(result)
            
            # Verify this result has the correct parameters
            assert key in result
            assert server in result
        
        # Verify all results are different and don't cross-contaminate
        for i, (key, server) in enumerate(configs):
            current_result = results[i]
            
            # Check this result has the right content
            assert key in current_result
            assert server in current_result
            
            # Check other keys/servers are not in this result
            for j, (other_key, other_server) in enumerate(configs):
                if i != j:
                    assert other_key not in current_result or other_key == key
                    assert other_server not in current_result or other_server == server
