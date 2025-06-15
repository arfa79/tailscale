# Test Suite for Tailscale Auto-Deployment

This directory contains all tests for the Tailscale exit node auto-deployment system.

## Structure

```
tests/
├── __init__.py                    # Makes tests a Python package
├── conftest.py                   # Shared pytest configuration and fixtures
├── test_cloud_init_generator.py  # Tests for CloudInitScriptGenerator
├── test_digital_ocean_client.py  # Tests for DigitalOceanClient (future)
├── test_config.py               # Tests for Config class (future)
└── integration/                 # Integration tests
    ├── __init__.py
    └── test_end_to_end.py       # End-to-end integration tests
```

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=digital_ocean

# Run specific test file
pytest tests/test_cloud_init_generator.py

# Run with verbose output
pytest tests/ -v

# Run only unit tests (exclude integration)
pytest tests/ -m "not integration"
```

## Test Categories

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test components working together
- **End-to-End Tests**: Test the complete workflow
