.PHONY: ui

ui:
	PYTHONPATH=src streamlit run src/app/ui_streamlit/main.py
