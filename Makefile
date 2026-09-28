.PHONY: install lint format test run clean

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .

test:
	pytest -q

run:
	python examples/search_to_json.py

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
