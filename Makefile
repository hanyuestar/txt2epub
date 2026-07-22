.PHONY: help lint format format-check test check

help:
	@echo make lint          Run Ruff lint checks
	@echo make lint-f        Run Ruff lint checks and fix issues
	@echo make format        Format code with Ruff
	@echo make format-check  Verify formatting without changing files
	@echo make test          Run unit tests
	@echo make check         Run all verification checks

lint:
	ruff check .

lint-f:
	ruff check . --fix

format:
	ruff format .

format-check:
	ruff format --check .

test:
	python -m unittest discover -s tests -v

check: lint format-check test
