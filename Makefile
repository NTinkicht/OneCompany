.PHONY: doctor validate simulate supervise reconcile

doctor:
	python onecompany.py doctor

validate:
	python onecompany.py validate
	python -m compileall -q scripts

simulate:
	python onecompany.py simulate
	python onecompany.py simulate-supervision

supervise:
	python onecompany.py supervise --force-observe

reconcile:
	python onecompany.py reconcile
