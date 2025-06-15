#!/usr/bin/env python3
"""
Test runner script for Tailscale auto-deployment system.

This script provides easy commands to run different types of tests.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n🔧 {description}")
    print(f"Running: {' '.join(cmd)}")
    print("-" * 50)
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    if result.returncode != 0:
        print(f"❌ {description} failed!")
        return False
    else:
        print(f"✅ {description} completed successfully!")
        return True


def main():
    parser = argparse.ArgumentParser(description="Test runner for Tailscale auto-deployment")
    parser.add_argument(
        "command",
        choices=["unit", "integration", "all", "coverage", "fast", "install-deps"],
        help="Type of tests to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Run tests with verbose output"
    )
    
    args = parser.parse_args()
    
    base_cmd = ["python", "-m", "pytest"]
    if args.verbose:
        base_cmd.append("-v")
    
    success = True
    
    if args.command == "install-deps":
        success = run_command(
            ["pip", "install", "-r", "tests/requirements.txt"],
            "Installing test dependencies"
        )
    
    elif args.command == "unit":
        success = run_command(
            base_cmd + ["tests/", "-m", "unit"],
            "Running unit tests"
        )
    
    elif args.command == "integration":
        success = run_command(
            base_cmd + ["tests/", "-m", "integration"],
            "Running integration tests"
        )
    
    elif args.command == "fast":
        success = run_command(
            base_cmd + ["tests/", "-m", "not slow"],
            "Running fast tests (excluding slow tests)"
        )
    
    elif args.command == "coverage":
        success = run_command(
            base_cmd + [
                "tests/",
                "--cov=digital_ocean",
                "--cov-report=html",
                "--cov-report=term-missing"
            ],
            "Running tests with coverage"
        )
        if success:
            print("\n📊 Coverage report generated in htmlcov/index.html")
    
    elif args.command == "all":
        success = run_command(
            base_cmd + ["tests/"],
            "Running all tests"
        )
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
