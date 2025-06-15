#!/usr/bin/env python3
"""
Tailscale Exit Node Auto-Deployment for DigitalOcean

A robust, automated system for deploying and managing Tailscale exit nodes
on DigitalOcean droplets using cloud-init for zero-touch deployment.
"""

import json
import logging
import os
import signal
import sys
import time
import threading
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

import digitalocean
import requests
import tenacity
from dotenv import load_dotenv


# Custom Exceptions
class TailscaleExitNodeError(Exception):
    """Base exception for Tailscale exit node operations."""
    pass


class DropletCreationError(TailscaleExitNodeError):
    """Raised when droplet creation fails."""
    pass


class NodeHealthCheckError(TailscaleExitNodeError):
    """Raised when node health check fails."""
    pass


class ConfigurationError(TailscaleExitNodeError):
    """Raised when configuration is invalid."""
    pass


# Configuration
@dataclass
class Config:
    """Application configuration."""
    do_token: str
    ts_authkey: str
    login_server: str = "https://controlplane.tailscale.com"
    region: str = "fra1"
    image_name: str = "ubuntu-22-04"
    name_prefix: str = "tailscale-exit"
    target_nodes: int = 1
    max_nodes: int = 3
    health_check_interval: int = 300
    log_level: str = "INFO"
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.do_token:
            raise ConfigurationError("DO_TOKEN is required")
        if not self.ts_authkey:
            raise ConfigurationError("TS_AUTHKEY is required")
        if self.target_nodes > self.max_nodes:
            raise ConfigurationError("target_nodes cannot exceed max_nodes")
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create configuration from environment variables."""
        load_dotenv()
        return cls(
            do_token=os.getenv("DO_TOKEN", ""),
            ts_authkey=os.getenv("TS_AUTHKEY", ""),
            login_server=os.getenv("LOGIN_SERVER", "https://controlplane.tailscale.com"),
            region=os.getenv("DO_REGION", "fra1"),
            image_name=os.getenv("DO_IMAGE", "ubuntu-22-04"),
            name_prefix=os.getenv("NAME_PREFIX", "tailscale-exit"),
            target_nodes=int(os.getenv("TARGET_EXIT_NODES", "1")),
            max_nodes=int(os.getenv("MAX_EXIT_NODES", "3")),
            health_check_interval=int(os.getenv("HEALTH_CHECK_INTERVAL", "300")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


# Logging Setup
def setup_logging(config: Config) -> logging.Logger:
    """Setup structured logging with file and console handlers."""
    logger = logging.getLogger("tailscale_autodeploy")
    logger.setLevel(getattr(logging, config.log_level.upper()))
    
    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    )
    
    # File handler
    log_file = Path("auto-deploy.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


@dataclass
class ExitNodeInfo:
    """Information about a Tailscale exit node."""
    droplet_id: str
    name: str
    public_ip: str
    tailscale_ip: str
    region: str
    status: str
    created_at: datetime
    last_checked: datetime

    @classmethod
    def from_dict(cls, data: Dict) -> 'ExitNodeInfo':
        """Create ExitNodeInfo from dictionary with datetime parsing."""
        return cls(
            droplet_id=data['droplet_id'],
            name=data['name'],
            public_ip=data['public_ip'],
            tailscale_ip=data['tailscale_ip'],
            region=data['region'],
            status=data['status'],
            created_at=datetime.fromisoformat(data['created_at']),
            last_checked=datetime.fromisoformat(data['last_checked'])
        )

    def to_dict(self) -> Dict:
        """Convert ExitNodeInfo to dictionary with datetime serialization."""
        return {
            'droplet_id': self.droplet_id,
            'name': self.name,
            'public_ip': self.public_ip,
            'tailscale_ip': self.tailscale_ip,
            'region': self.region,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'last_checked': self.last_checked.isoformat()
        }


class CloudInitScriptGenerator:
    """Generates cloud-init scripts for Tailscale setup."""
    
    def __init__(self, shells_path: Optional[Union[str, Path]] = None):
        """Initialize with path to shells directory."""
        base_path = Path(__file__).parent.parent
        self.shells_path = Path(shells_path) if shells_path else base_path / "shells"
        
        self.setup_script_path = self.shells_path / "tailscale-exit-node-setup.bash"
        self.cloud_init_wrapper_path = self.shells_path / "cloud-init-wrapper.bash"

        if not self.setup_script_path.exists():
            raise FileNotFoundError(f"Setup script not found: {self.setup_script_path}")
        if not self.cloud_init_wrapper_path.exists():
            raise FileNotFoundError(f"Cloud-init wrapper script not found: {self.cloud_init_wrapper_path}")

    def generate_tailscale_script(self, ts_authkey: str, login_server: str) -> str:
        """Generate cloud-init script using external wrapper and setup scripts."""
        setup_script_content = self.setup_script_path.read_text()
        cloud_init_wrapper_content = self.cloud_init_wrapper_path.read_text()
        
        # Replace placeholders in the wrapper script
        return cloud_init_wrapper_content.format(
            ts_authkey=ts_authkey,
            login_server=login_server,
            setup_script_content=setup_script_content
        )


class DigitalOceanClient:
    """Wrapper for DigitalOcean API operations."""
    
    def __init__(self, token: str, logger: logging.Logger):
        self.manager = digitalocean.Manager(token=token)
        self.logger = logger
        self._droplets_cache: Optional[List[digitalocean.Droplet]] = None
        self._cache_time: Optional[float] = None
        self.cache_ttl_seconds: int = 60  # 1 minute cache
    
    def get_droplets(self, force_refresh: bool = False) -> List[digitalocean.Droplet]:
        """Get all droplets with caching."""
        now = time.time()
        if (
            force_refresh or 
            self._droplets_cache is None or 
            self._cache_time is None or 
            (now - self._cache_time) > self.cache_ttl_seconds
        ):
            try:
                self._droplets_cache = self.manager.get_all_droplets()
                self._cache_time = now
                self.logger.debug(f"Refreshed droplets cache: {len(self._droplets_cache)} droplets")
            except Exception as e:
                self.logger.error(f"Failed to fetch droplets from DigitalOcean: {e}")
                return self._droplets_cache or []
        
        return self._droplets_cache if self._droplets_cache is not None else []
    
    def get_regions(self) -> List[digitalocean.Region]:
        """Get all available regions."""
        return self.manager.get_all_regions()
    
    def get_sizes(self) -> List[digitalocean.Size]:
        """Get all available sizes."""
        return self.manager.get_all_sizes()
    
    def get_images(self) -> List[digitalocean.Image]:
        """Get all available images."""
        return self.manager.get_global_images()
    
    def get_droplet(self, droplet_id: Union[str, int]) -> digitalocean.Droplet:
        """Get a specific droplet by ID."""
        return self.manager.get_droplet(droplet_id)
    
    def get_action(self, action_id: Union[str, int]) -> digitalocean.Action:
        """Get a specific action by ID."""
        return self.manager.get_action(action_id)


class TailscaleExitNodeManager:
    """Manages DigitalOcean droplets for Tailscale exit nodes."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.do_client = DigitalOceanClient(config.do_token, logger)
        self.cloud_init_generator = CloudInitScriptGenerator()
        self.lock = threading.Lock()
        self.shutdown_requested = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.droplets: List[digitalocean.Droplet] = []
        self.regions: List[digitalocean.Region] = []
        self.sizes: List[digitalocean.Size] = []
        self.images: List[digitalocean.Image] = []
        self.region: Optional[digitalocean.Region] = None
        self.size: Optional[digitalocean.Size] = None

        self._init_do_resources()
        
        self.exit_nodes_file = Path("exit_nodes.json")
        self.exit_nodes: List[ExitNodeInfo] = self._load_exit_nodes()

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        signal_name = signal.Signals(signum).name
        self.logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self.shutdown_requested = True

    def _init_do_resources(self) -> None:
        """Initialize DO resources with error handling."""
        try:
            self.droplets = self.do_client.get_droplets(force_refresh=True)
            self.regions = self.do_client.get_regions()
            self.sizes = self.do_client.get_sizes()
            self.images = self.do_client.get_images()
            
            self.logger.info(f"Initialized with {len(self.droplets)} droplets from DigitalOcean account.")
            
            self.region = self._find_region(self.config.region)
            self._validate_image_availability()
            self.size = self._select_optimal_size()
            
        except Exception as e:
            self.logger.error(f"Fatal error during DigitalOcean resource initialization: {e}")
            raise ConfigurationError(f"DO resource initialization failed: {e}")

    def _find_region(self, region_slug: str) -> digitalocean.Region:
        """Find and validate the specified region."""
        for r in self.regions:
            if r.slug == region_slug:
                return r
        available_slugs = [r.slug for r in self.regions]
        raise ConfigurationError(f"Region '{region_slug}' not found. Available: {available_slugs}")

    def _validate_image_availability(self) -> None:
        """Validate that the specified image exists."""
        if not any(self.config.image_name in image.slug for image in self.images if image.slug):
            available_images = [img.slug for img in self.images if img.slug]
            raise ConfigurationError(
                f"Image slug containing '{self.config.image_name}' not found. "
                f"Check DO_IMAGE. Available image slugs (sample): {available_images[:5]}"
            )

    def _select_optimal_size(self) -> digitalocean.Size:
        """Select the cheapest size that meets minimum requirements in the target region."""
        if not self.region:
            raise ConfigurationError("Region not initialized, cannot select size.")

        valid_sizes = [
            s for s in self.sizes 
            if (self.region.slug in s.regions and 
                s.memory >= 1000 and
                s.price_monthly is not None)
        ]
        
        if not valid_sizes:
            raise ConfigurationError(f"No suitable size (>=1GB RAM) found in region {self.region.slug}")
            
        selected_size = min(valid_sizes, key=lambda x: x.price_monthly)
        self.logger.info(f"Selected optimal size: {selected_size.slug} (${selected_size.price_monthly}/month)")
        return selected_size

    def _load_exit_nodes(self) -> List[ExitNodeInfo]:
        """Load exit nodes info from JSON file"""
        if self.exit_nodes_file.exists():
            try:
                with open(self.exit_nodes_file, 'r') as f:
                    data = json.load(f)
                return [ExitNodeInfo.from_dict(node_data) for node_data in data]
            except json.JSONDecodeError as e:
                self.logger.warning(f"Error decoding JSON from {self.exit_nodes_file}: {e}. Starting with empty list.")
            except Exception as e:
                self.logger.warning(f"Failed to load or parse {self.exit_nodes_file}: {e}. Starting with empty list.")
        return []

    def _save_exit_nodes(self):
        """Save exit nodes info to JSON file"""
        try:
            data_to_save = [node.to_dict() for node in self.exit_nodes]
            with open(self.exit_nodes_file, 'w') as f:
                json.dump(data_to_save, f, indent=2)
            self.logger.debug(f"Saved {len(data_to_save)} exit nodes to {self.exit_nodes_file}")
        except Exception as e:
            self.logger.error(f"Failed to save exit nodes to {self.exit_nodes_file}: {e}")

    def _get_node_status(self, droplet: digitalocean.Droplet) -> Optional[Dict]:
        """Get comprehensive node status via HTTP."""
        if not droplet.ip_address:
            self.logger.warning(f"Droplet {droplet.name} (ID: {droplet.id}) has no public IP address.")
            return None
        
        try:
            ipaddress.ip_address(droplet.ip_address)
            status_info = self._get_status_via_http(droplet.ip_address)
            
            return {
                'public_ip': droplet.ip_address,
                'tailscale_ip': status_info.get('tailscale_ip'),
                'is_reachable': status_info.get('is_ready', False),
                'tailscale_status': status_info.get('tailscale_status', {})
            }
        except ValueError:
            self.logger.error(f"Invalid IP address format for droplet {droplet.name}: {droplet.ip_address}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get node status for {droplet.name} (IP: {droplet.ip_address}): {e}")
            return None

    def _get_status_via_http(self, ip: str) -> Dict:
        """Get status via HTTP endpoints."""
        try:
            setup_response = requests.get(f"http://{ip}:8080/setup-complete", timeout=10)
            if setup_response.status_code != 200:
                self.logger.debug(f"HTTP: {ip}:8080/setup-complete returned {setup_response.status_code}")
                return {'is_ready': False}
            
            ts_ip_response = requests.get(f"http://{ip}:8080/tailscale-ip.txt", timeout=5)
            ts_ip = ts_ip_response.text.strip() if ts_ip_response.status_code == 200 else ""
            
            ts_status_response = requests.get(f"http://{ip}:8080/tailscale-status.json", timeout=5)
            ts_status_data = ts_status_response.json() if ts_status_response.status_code == 200 else {}
            
            return {
                'is_ready': True,
                'tailscale_ip': ts_ip,
                'tailscale_status': ts_status_data
            }
        except requests.RequestException as e:
            self.logger.debug(f"HTTP status check failed for {ip}: {e}")
            return {'is_ready': False}    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(Exception),
        wait=tenacity.wait_exponential(multiplier=1, min=5, max=60),
        stop=tenacity.stop_after_attempt(3),
        before_sleep=tenacity.before_sleep_log(logging.getLogger("tailscale_autodeploy"), logging.WARNING)
    )
    def _create_droplet(self) -> digitalocean.Droplet:
        """Create droplet with cloud-init for full automation."""
        droplet_name = f"{self.config.name_prefix}-{self.region.slug}-{int(time.time())}"
        
        cloud_init_script = self.cloud_init_generator.generate_tailscale_script(
            self.config.ts_authkey, 
            self.config.login_server
        )

        image_obj = next((img for img in self.images if self.config.image_name in img.slug and img.slug is not None), None)
        if not image_obj:
            raise DropletCreationError(f"Image slug containing '{self.config.image_name}' not found or has no ID.")

        droplet = digitalocean.Droplet(
            token=self.do_client.manager.token,
            name=droplet_name,
            region=self.region.slug,
            image=image_obj.id,
            size_slug=self.size.slug,
            ssh_keys=[], 
            tags=['tailscale-exit-node', 'auto-managed'],
            user_data=cloud_init_script,
            backups=False
        )
        
        self.logger.info(f"Attempting to create droplet: {droplet_name} in {self.region.slug} with image {image_obj.slug}")
        droplet.create()
        self.logger.info(f"Droplet creation initiated for {droplet_name} (Action ID: {droplet.action_ids[-1] if droplet.action_ids else 'N/A'})")
        
        # Wait for creation to complete
        action = self.do_client.get_action(droplet.action_ids[-1])
        action.wait(update_every_seconds=10)
        
        # Refresh droplet object to get IP and full status
        created_droplet = self.do_client.get_droplet(droplet.id)
        if not created_droplet.ip_address:
            raise DropletCreationError(f"Droplet {created_droplet.name} created but no IP address was assigned.")
            
        self.logger.info(f"Droplet {created_droplet.name} created successfully with IP: {created_droplet.ip_address}")
        return created_droplet    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(NodeHealthCheckError),
        wait=tenacity.wait_fixed(30),
        stop=tenacity.stop_after_attempt(10),
        before_sleep=tenacity.before_sleep_log(logging.getLogger("tailscale_autodeploy"), logging.INFO)
    )
    def _wait_for_http_ready(self, ip: str, timeout_per_attempt: int = 20) -> bool:
        """Wait for HTTP endpoint on the droplet to become responsive."""
        self.logger.info(f"Waiting for HTTP service on {ip}:8080 to be ready...")
        try:
            response = requests.get(f"http://{ip}:8080/setup-complete", timeout=timeout_per_attempt)
            if response.status_code == 200:
                self.logger.info(f"HTTP service on {ip}:8080 is ready!")
                return True
        except requests.RequestException as e:
            self.logger.debug(f"HTTP readiness check for {ip} failed: {e}")
        raise NodeHealthCheckError(f"HTTP service on {ip}:8080 not ready after multiple attempts.")
    def _provision_single_node(self) -> Optional[ExitNodeInfo]:
        """Provision a single exit node. Returns ExitNodeInfo if successful."""
        droplet = None
        try:
            droplet = self._create_droplet()
            self._wait_for_http_ready(droplet.ip_address)
            
            node_status_data = self._get_node_status(droplet)
            if not node_status_data or not node_status_data.get('is_reachable'):
                raise NodeHealthCheckError(f"Node {droplet.name} failed post-provisioning health check.")
            
            return ExitNodeInfo(
                droplet_id=str(droplet.id),
                name=droplet.name,
                public_ip=droplet.ip_address,
                tailscale_ip=node_status_data.get('tailscale_ip', "unknown"),
                region=self.region.slug,
                status='healthy',
                created_at=datetime.now(timezone.utc),
                last_checked=datetime.now(timezone.utc)
            )
        except Exception as e:
            self.logger.error(f"Failed to provision node: {e}")
            if droplet:
                try:
                    self.logger.warning(f"Attempting to destroy failed droplet {droplet.name} (ID: {droplet.id})")
                    droplet.destroy()
                    self.logger.info(f"Successfully destroyed failed droplet {droplet.name}")
                except Exception as cleanup_error:
                    self.logger.error(f"Failed to destroy failed droplet {droplet.name}: {cleanup_error}")
            return None

    def _provision_nodes(self, count: int) -> None:
        """Provision multiple nodes."""
        successful_nodes: List[ExitNodeInfo] = []
        with ThreadPoolExecutor(max_workers=min(count, 3), thread_name_prefix="ProvisionWorker") as executor:
            futures = {executor.submit(self._provision_single_node): i for i, _ in enumerate(range(count))}
            
            for future in as_completed(futures):
                node_index = futures[future]
                try:
                    node_info = future.result()
                    if node_info:
                        successful_nodes.append(node_info)
                        self.logger.info(f"Successfully provisioned node {node_info.name} (Worker {node_index})")
                except Exception as e:
                    self.logger.error(f"Error provisioning node (Worker {node_index}): {e}")
        
        if successful_nodes:
            with self.lock:
                self.exit_nodes.extend(successful_nodes)
    def _check_existing_nodes(self) -> List[ExitNodeInfo]:
        """Check health of existing nodes."""
        healthy_nodes: List[ExitNodeInfo] = []
        current_do_droplets = {str(d.id): d for d in self.do_client.get_droplets()}

        nodes_to_remove_from_tracking = []

        for node_info in self.exit_nodes:
            try:
                if node_info.droplet_id not in current_do_droplets:
                    self.logger.warning(f"Node {node_info.name} (ID: {node_info.droplet_id}) tracked but not found in DigitalOcean. Marking for removal from tracking.")
                    nodes_to_remove_from_tracking.append(node_info)
                    continue

                droplet = current_do_droplets[node_info.droplet_id]
                
                if droplet.status == 'active':
                    node_status_data = self._get_node_status(droplet)
                    if node_status_data and node_status_data.get('is_reachable'):
                        node_info.status = 'healthy'
                        node_info.tailscale_ip = node_status_data.get('tailscale_ip', node_info.tailscale_ip)
                        node_info.last_checked = datetime.now(timezone.utc)
                        healthy_nodes.append(node_info)
                        self.logger.debug(f"Node {node_info.name} health check PASSED")
                    else:
                        node_info.status = 'unhealthy'
                        node_info.last_checked = datetime.now(timezone.utc)
                        self.logger.warning(f"Node {node_info.name} health check FAILED")
                else:
                    node_info.status = 'unhealthy'
                    self.logger.warning(f"Node {node_info.name} (ID: {node_info.droplet_id}) found in DigitalOcean but status is '{droplet.status}'. Marked unhealthy.")
            
            except Exception as e:
                self.logger.error(f"Error during health check for node {node_info.name} (ID: {node_info.droplet_id}): {e}. Marked as error.")
                node_info.status = 'error'

        # Remove nodes that are tracked but no longer exist on DO
        if nodes_to_remove_from_tracking:
            with self.lock:
                for node_to_remove in nodes_to_remove_from_tracking:
                    self.exit_nodes.remove(node_to_remove)
                self.logger.info(f"Removed {len(nodes_to_remove_from_tracking)} untracked/non-existent nodes from internal list.")
        
        return healthy_nodes

    def _cleanup_failed_nodes(self) -> None:
        """Clean up unhealthy or failed nodes."""
        nodes_to_permanently_remove: List[ExitNodeInfo] = []
        
        for node_info in self.exit_nodes:
            if node_info.status in ['unhealthy', 'error']:
                self.logger.warning(f"Node {node_info.name} (ID: {node_info.droplet_id}) is in status '{node_info.status}'. Evaluating for cleanup.")
                try:
                    droplet = self.do_client.get_droplet(node_info.droplet_id)
                    self.logger.info(f"Destroying droplet {droplet.name} (ID: {droplet.id}) due to failed health checks")
                    droplet.destroy()
                    self.logger.info(f"Successfully destroyed droplet {droplet.name}")
                except Exception as destroy_error:
                    self.logger.error(f"Failed to destroy droplet {node_info.name} (ID: {node_info.droplet_id}): {destroy_error}")
                
                nodes_to_permanently_remove.append(node_info)
        
        if nodes_to_permanently_remove:
            with self.lock:
                for node in nodes_to_permanently_remove:
                    self.exit_nodes.remove(node)
                self.logger.info(f"Removed {len(nodes_to_permanently_remove)} failed nodes from tracking")

    def run(self) -> None:
        """Main run loop for continuous operation."""
        self.logger.info("Starting Tailscale exit node auto-deployment manager...")
        self.logger.info(f"Configuration: Target nodes: {self.config.target_nodes}, Max nodes: {self.config.max_nodes}, Health check interval: {self.config.health_check_interval}s")
        
        while not self.shutdown_requested:
            try:
                self.logger.info("Starting management cycle...")
                
                # Check existing nodes
                healthy_nodes = self._check_existing_nodes()
                self.logger.info(f"Found {len(healthy_nodes)} healthy nodes out of {len(self.exit_nodes)} tracked nodes")
                
                # Clean up failed nodes
                self._cleanup_failed_nodes()
                
                # Determine if we need more nodes
                current_healthy_count = len([n for n in self.exit_nodes if n.status == 'healthy'])
                needed = max(0, self.config.target_nodes - current_healthy_count)
                
                if needed > 0:
                    if len(self.exit_nodes) + needed <= self.config.max_nodes:
                        self.logger.info(f"Need {needed} more nodes to reach target of {self.config.target_nodes}")
                        self._provision_nodes(needed)
                    else:
                        max_can_create = max(0, self.config.max_nodes - len(self.exit_nodes))
                        if max_can_create > 0:
                            self.logger.warning(f"Would need {needed} nodes but limited by max_nodes. Creating {max_can_create} nodes.")
                            self._provision_nodes(max_can_create)
                        else:
                            self.logger.warning(f"Cannot create more nodes: already at max_nodes limit ({self.config.max_nodes})")
                else:
                    self.logger.info("Target node count reached, no provisioning needed")
                
                # Save current state
                self._save_exit_nodes()
                
                self.logger.info(f"Management cycle complete. Sleeping for {self.config.health_check_interval} seconds...")
                
                # Sleep with shutdown check
                for _ in range(self.config.health_check_interval):
                    if self.shutdown_requested:
                        break
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                self.logger.info("Received interrupt signal, shutting down...")
                break
            except Exception as e:
                self.logger.error(f"Unhandled error in management loop: {e}", exc_info=True)
                self.logger.info("Sleeping for 60 seconds due to error before retrying cycle.")
                time.sleep(60)
        
        self.logger.info("Shutdown complete.")


def main() -> None:
    """Main entry point."""
    logger = None
    try:
        config = Config.from_env()
        logger = setup_logging(config)
        
        logger.info("Application starting...")
        manager = TailscaleExitNodeManager(config, logger)
        manager.run()
        logger.info("Application finished.")
        
    except ConfigurationError as e:
        if logger:
            logger.critical(f"Configuration error: {e}", exc_info=True)
        else:
            print(f"CRITICAL Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        if logger:
            logger.info("Application shutdown requested by user (KeyboardInterrupt in main).")
        else:
            print("\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        if logger:
            logger.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
        else:
            print(f"CRITICAL Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()