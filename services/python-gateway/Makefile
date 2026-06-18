# Makefile for smol-brain Python gateway
.PHONY: help install dev test lint format check clean build run

help:
	@echo "Available commands:"
	@echo "  install     Install dependencies (including dev)"
	@echo "  dev         Run in development mode (auto-reload)"
	@echo "  test        Run unit tests"
	@echo "  lint        Run linters (ruff, mypy)"
	@echo "  format      Format code (ruff format)"
	@echo "  check       Run all checks (lint + test)"
	@echo "  clean       Remove cache files"
	@echo "  build       Build Docker image"
	@echo "  run         Run via gunicorn (production mode)"

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

test:
	python -m pytest tests/ -v --tb=short

lint:
	ruff check .
	mypy app tests

format:
	ruff format .
	ruff check --fix .

check: lint test

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

build:
	docker build -t smol-brain-python-gateway:latest .

run:
	gunicorn app.main:app -c gunicorn_conf.py
