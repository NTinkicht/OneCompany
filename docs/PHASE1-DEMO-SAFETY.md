# Run the disposable demo safely

`python onecompany.py demo` exercises the existing disposable Create/Adopt-to-local-CRUD proof. Use synthetic information only. The demo is localhost-only evidence: it is not a public deployment, does not prove production readiness, does not grant Product Brief or Work Unit approval, and does not establish an independent review or trusted live revision. Stop the local process when finished; disposable data is not customer storage.


The real `demo` entry point invokes `demo_safety.require_safe_demo` on the **already-bound fixture** before starting its HTTP worker. The guard checks the actual bound IP is loopback, the actual SQLite store has only an empty in-memory database, and planning still states `READ_ONLY_PROPOSAL` / `NOT_GRANTED`. An unverified fixture is refused and closed; command-line claims about locality, synthetic data, or approval do not count as safety evidence.
