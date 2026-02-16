.PHONY: ui pull setup setup-python setup-system setup-system-linux setup-system-windows

ui:
	PYTHONPATH=src streamlit run src/app/ui_streamlit/main.py

pull:
	git pull

setup: setup-python setup-system
	@echo "Setup complete. Run 'make ui' to start the app."

setup-python:
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv is not installed. Install it first: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	uv sync

setup-system:
	@if command -v apt-get >/dev/null 2>&1; then \
		$(MAKE) setup-system-linux; \
	elif command -v winget >/dev/null 2>&1 || command -v choco >/dev/null 2>&1; then \
		$(MAKE) setup-system-windows; \
	else \
		echo "Skipping system package install (apt-get not found)."; \
		echo "Install system OCR dependencies manually (Tesseract OCR and Poppler)."; \
	fi

setup-system-linux:
	@echo "Installing system OCR dependencies (Ubuntu/Debian)..."
	sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-ara poppler-utils

setup-system-windows:
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
