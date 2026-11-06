.PHONY: test build integration audit

test:
	python3 -B -I -m unittest discover -s tests

build:
	python3 -I tools/build.py

integration: build
	python3 -I tools/integration_test.py

audit:
	python3 -I tools/privacy_scan.py
