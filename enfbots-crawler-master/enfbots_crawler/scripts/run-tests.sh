#!/bin/sh
set -e

echo "Static type checking"
mypy --config=pyproject.toml \
	--ignore-missing-imports \
	tests/ \
	enfbots_crawler/

echo "Running tests"

pytest --cov-append \
	-c pyproject.toml \
	--cov=enfbots_crawler \
	--junitxml=report_enfbots.xml \
	tests/enfbots_crawler/unit \
	tests/enfbots_crawler/integration

