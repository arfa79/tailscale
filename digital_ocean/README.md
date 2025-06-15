# Tailscale Exit Node Auto-Deployment

A robust, automated system for deploying and managing Tailscale exit nodes on DigitalOcean droplets using cloud-init for zero-touch deployment.

## Features

- **Zero SSH Dependencies**: Complete automation via cloud-init and HTTP status endpoints
- **Automatic Health Monitoring**: Continuous monitoring and replacement of failed nodes
- **Graceful Shutdown**: Proper signal handling for clean termination
- **Persistent State**: Node information stored in JSON for recovery
- **Concurrent Provisioning**: Parallel node creation for faster deployment
- **Comprehensive Logging**: Structured logging to both file and console
- **Configuration-Driven**: All settings via environment variables

## Requirements

- Python 3.8+
- DigitalOcean API token
- Tailscale/Headscale pre-auth key

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd Tailscale/digital_ocean
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp template.env .env
# Edit .env with your actual values
```

## Configuration

Copy `template.env` to `.env` and configure the following variables:

### Required Variables

- `DO_TOKEN`: Your DigitalOcean API token
- `TS_AUTHKEY`: Your Tailscale/Headscale pre-auth key

### Optional Variables

- `DO_REGION`: DigitalOcean region (default: fra1)
- `DO_IMAGE`: Ubuntu image to use (default: ubuntu-22-04)
- `LOGIN_SERVER`: Tailscale/Headscale server URL
- `NAME_PREFIX`: Prefix for droplet names (default: tailscale-exit)
- `TARGET_EXIT_NODES`: Number of exit nodes to maintain (default: 1)
- `MAX_EXIT_NODES`: Maximum number of exit nodes (default: 3)
- `HEALTH_CHECK_INTERVAL`: Health check interval in seconds (default: 300)
- `LOG_LEVEL`: Logging level (default: INFO)

## Usage

### Basic Usage

```bash
python auto-deploy.py
```

### Running as a Service

The script runs continuously and maintains the desired number of healthy exit nodes. It will:

1. Check existing nodes health via HTTP endpoints
2. Clean up failed/unreachable nodes
3. Provision new nodes if below target count
4. Save state to `exit_nodes.json`
5. Wait for the health check interval and repeat

### Graceful Shutdown

The script handles `SIGINT` (Ctrl+C) and `SIGTERM` signals gracefully:

```bash
# To stop the script
Ctrl+C
```

## Architecture

### Classes

- **Config**: Configuration management with validation
- **ExitNodeInfo**: Data class for node information
- **CloudInitScriptGenerator**: Generates cloud-init scripts for Tailscale setup
- **DigitalOceanClient**: Wrapper for DigitalOcean API operations with caching
- **TailscaleExitNodeManager**: Main orchestrator for node lifecycle management

### Key Features

1. **Cloud-Init Automation**: Complete Tailscale setup without SSH
2. **HTTP Status Endpoints**: Node health checking via HTTP on port 8080
3. **Automatic Cleanup**: Failed nodes are detected and removed
4. **Concurrent Operations**: Multiple nodes provisioned in parallel
5. **State Persistence**: Node information saved to JSON file
6. **Error Recovery**: Robust error handling with exponential backoff

## Monitoring

The script provides comprehensive logging:

- **File Logging**: All events logged to `auto-deploy.log`
- **Console Logging**: Real-time status updates
- **Structured Format**: Timestamp, level, function, and line number

### Log Levels

- `DEBUG`: Detailed debugging information
- `INFO`: General operational messages
- `WARNING`: Non-critical issues
- `ERROR`: Error conditions

## Security

- **No SSH Keys Required**: Zero SSH dependency eliminates key management
- **Environment Variables**: Sensitive data stored in environment variables
- **Minimal Permissions**: Only required DigitalOcean permissions needed

## Troubleshooting

### Common Issues

1. **Configuration Errors**: Check `.env` file for correct values
2. **API Rate Limits**: Script includes exponential backoff for retries
3. **Network Issues**: HTTP endpoints may take time to become available
4. **Node Health**: Check `exit_nodes.json` for node status

### Debug Mode

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
python auto-deploy.py
```

### Manual Cleanup

To manually clean up all managed droplets:

```bash
# List droplets with tags
doctl compute droplet list --tag-name tailscale-exit-node

# Delete all tagged droplets
doctl compute droplet delete --tag-name tailscale-exit-node
```

## Development

### Code Structure

```
digital_ocean/
├── auto-deploy.py      # Main application
├── requirements.txt    # Python dependencies
├── template.env       # Environment template
├── .env              # Your configuration (gitignored)
├── exit_nodes.json   # Node state (auto-generated)
└── auto-deploy.log   # Application logs
```

### Best Practices

- Type hints for all functions
- Comprehensive error handling
- Structured logging
- Configuration validation
- Resource cleanup
- Signal handling
- Documentation

## License

This project is licensed under the MIT License.
