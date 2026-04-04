.PHONY: install install-cpu client doctor run clean test test-cov

install:       ## Auto-detect GPU and install everything
	bash install.sh

install-cpu:   ## Install for CPU-only
	bash install.sh --cpu

client:        ## Build Angular frontend
	cd client && npm ci && npx ng build

doctor:        ## Run diagnostic checks
	python facet.py --doctor

run:           ## Start the web viewer
	python viewer.py

clean:         ## Remove venv and build artifacts
	rm -rf venv client/dist client/node_modules

test:          ## Run Python test suite
	python3 -m pytest

test-cov:      ## Run tests with coverage report
	python3 -m pytest --cov=api --cov=config --cov=storage --cov-report=term-missing

help:          ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
