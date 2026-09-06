# Makefile for OpenGlassBox Python port development
# Provides convenient commands for common development tasks

.PHONY: help install install-dev test test-coverage test-all lint format clean build dist upload docs run-demo run-enhanced-demo

# Default target
help:
	@echo "OpenGlassBox Python Port - Development Commands"
	@echo ""
	@echo "Setup and Installation:"
	@echo "  install         Install package in current environment"
	@echo "  install-dev     Install package with development dependencies"
	@echo "  clean           Clean build artifacts and cache files"
	@echo ""
	@echo "Testing:"
	@echo "  test            Run basic test suite"
	@echo "  test-coverage   Run tests with coverage report"
	@echo "  test-all        Run all tests including slow and integration tests"
	@echo "  test-debug      Run debug UI specific tests"
	@echo "  test-demo       Run demo integration tests"
	@echo "  test-performance Run performance benchmarks"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint            Run linters (flake8, mypy)"
	@echo "  format          Format code with black and isort"
	@echo "  check-format    Check if code formatting is correct"
	@echo ""
	@echo "Building and Distribution:"
	@echo "  build           Build package distributions"
	@echo "  dist            Create distribution packages"
	@echo "  upload          Upload to PyPI (requires credentials)"
	@echo ""
	@echo "Documentation:"
	@echo "  docs            Generate documentation"
	@echo "  docs-serve      Serve documentation locally"
	@echo ""
	@echo "Demo Applications:"
	@echo "  run-demo        Run the basic demo"
	@echo "  run-enhanced    Run the enhanced demo with debug UI"
	@echo ""

# Installation targets
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

# Testing targets
test:
	python -m pytest tests/ -v

test-coverage:
	python -m pytest tests/ -v --cov=openglassbox --cov-report=term-missing --cov-report=html

test-all:
	python -m pytest tests/ -v --cov=openglassbox --cov-report=term-missing --cov-report=html --runslow

test-debug:
	python -m pytest tests/test_debug_ui.py -v

test-demo:
	python -m pytest tests/test_demo_integration.py -v

test-performance:
	python -m tests.test_performance_benchmarks

# Code quality targets
lint:
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 . --count --exit-zero --max-complexity=10 --max-line-length=88 --statistics
	mypy . --ignore-missing-imports

format:
	black .
	isort .

check-format:
	black --check .
	isort --check-only .

# Build and distribution targets
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python -m build

dist: build
	ls -la dist/

upload: dist
	python -m twine upload dist/*

# Documentation targets
docs:
	@echo "Documentation generation not yet implemented"
	@echo "TODO: Add Sphinx documentation generation"

docs-serve:
	@echo "Documentation serving not yet implemented"
	@echo "TODO: Add Sphinx documentation server"

# Demo targets
run-demo:
	python -m demo.src.main

run-enhanced:
	@echo "Enhanced demo not yet available as a separate entry point."
	@echo "Use: python -m demo.src.main"

# Development environment setup
dev-setup:
	conda env create -f environment.yml
	@echo ""
	@echo "Development environment created!"
	@echo "Activate with: conda activate openglassbox"

# Check dependencies
check-deps:
	pip list --outdated
	pip check

# Run all quality checks
quality: check-format lint test

# Complete CI/CD pipeline simulation
ci: clean install-dev quality test-coverage
	@echo ""
	@echo "✅ All CI checks passed!"
	@echo "Package is ready for release."
