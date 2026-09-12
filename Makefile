.PHONY: doctor status validate simulate check reconcile

doctor:
	python onecompany.py doctor

status:
	python onecompany.py status --live

validate:
	python onecompany.py validate

simulate:
	python onecompany.py simulate
	python onecompany.py simulate-ledger
	python onecompany.py simulate-supervision

check:
	python onecompany.py check

reconcile:
	python onecompany.py reconcile
