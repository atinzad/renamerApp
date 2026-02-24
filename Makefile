.PHONY: help ui pull setup setup-python setup-system setup-system-linux setup-system-macos setup-system-windows db-backup

DB_PATH ?= ./app.db
BACKUP_DIR ?= ./backups

help: ## Show available Make shortcuts
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

ui: ## Start the Streamlit UI
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		if [ -f ".venv/bin/activate" ]; then \
			echo "Activating .venv (POSIX)..."; \
			. .venv/bin/activate; \
		elif [ -f ".venv/Scripts/activate" ]; then \
			echo "Activating .venv (Windows)..."; \
			. .venv/Scripts/activate; \
		else \
			echo ".venv not found. Run 'make setup-python' first."; \
			exit 1; \
		fi; \
	fi; \
	PYTHONPATH=src streamlit run src/app/ui_streamlit/main.py

pull: ## Pull latest changes from origin
	git pull

setup: setup-python setup-system ## First-time bootstrap (Python deps + OCR system deps)
	@echo "Setup complete. Run 'make ui' to start the app."

setup-python: ## Install Python dependencies with uv
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv is not installed. Install it first: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	uv sync

setup-system: ## Install OCR system dependencies (auto-detect OS/package manager)
	@if command -v apt-get >/dev/null 2>&1; then \
		$(MAKE) setup-system-linux; \
	elif command -v brew >/dev/null 2>&1; then \
		$(MAKE) setup-system-macos; \
	elif command -v winget >/dev/null 2>&1 || command -v choco >/dev/null 2>&1; then \
		$(MAKE) setup-system-windows; \
	else \
		echo "Skipping system package install (no supported package manager found)."; \
		echo "Install system OCR dependencies manually (Tesseract OCR and Poppler)."; \
	fi

setup-system-linux: ## Install OCR system dependencies on Ubuntu/Debian
	@echo "Installing system OCR dependencies (Ubuntu/Debian)..."
	sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-ara poppler-utils

setup-system-macos: ## Install OCR system dependencies on macOS (Homebrew)
	@echo "Installing system OCR dependencies (macOS/Homebrew)..."
	@command -v brew >/dev/null 2>&1 || { \
		echo "Homebrew is not installed. Install it first: https://brew.sh/"; \
		exit 1; \
	}
	brew install tesseract poppler
	@brew info tesseract-lang >/dev/null 2>&1 && brew install tesseract-lang || true

setup-system-windows: ## Install OCR system dependencies on Windows (winget/choco)
	@if command -v winget >/dev/null 2>&1; then \
		echo "Installing system OCR dependencies (Windows/winget)..."; \
		winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements; \
		winget install -e --id oschwartz10612.Poppler --accept-package-agreements --accept-source-agreements; \
	elif command -v choco >/dev/null 2>&1; then \
		echo "Installing system OCR dependencies (Windows/choco)..."; \
		choco install -y tesseract poppler; \
	else \
		echo "No Windows package manager detected (winget/choco)."; \
		echo "Install Tesseract OCR + Poppler manually and add them to PATH."; \
		exit 1; \
	fi

db-backup: ## Backup SQLite DB to backups/ with timestamp (override DB_PATH=...)
	@mkdir -p "$(BACKUP_DIR)"
	@[ -f "$(DB_PATH)" ] || { echo "DB not found at $(DB_PATH)"; exit 1; }
	@backup_file="$(BACKUP_DIR)/app-$(shell date +%Y%m%d-%H%M%S).db"; \
	cp "$(DB_PATH)" "$$backup_file"; \
	echo "Backup created: $$backup_file"
