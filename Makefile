.PHONY: doctor validate simulate reconcile

doctor:
	python scripts/doctor.py

validate:
	python scripts/validate.py
	python -m compileall -q scripts

simulate:
	python scripts/simulate.py

reconcile:
	python scripts/reconcile.py
