.PHONY: test lint typecheck doctor

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy

doctor:
	kgmon kaggle doctor
