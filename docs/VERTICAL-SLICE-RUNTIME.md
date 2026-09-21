# First real local application runtime (WU-P1-RUNTIME-001)

The previous guided Create/Adopt and harness are *planning/admission* building blocks. This separate fixture is an actual runnable, disposable application and real HTTP backend. It is **not** an approved or publicly deployed customer project, a OneCompany hosted preview, or an autonomous worker runtime.

## Start and stop

Requires only Python 3.12+; no pip install, paid API, external database, browser service, GitHub credential or cloud resource.

\`\`\`sh
python examples/vertical-slice/vertical_app.py --port 8765
# Open http://127.0.0.1:8765/ on the same machine
# Stop with Ctrl+C; in-memory tasks are discarded.
python -m unittest discover -s .onecompany/selftest -p 'test_vertical_slice.py'
\`\`\`

The server binds **only 127.0.0.1**, validates the Host header, serves local HTML/JS with a restrictive CSP, never interpolates item titles as HTML, uses parameterized SQLite queries in memory, and accepts bounded JSON bodies and titles. It has GET /healthz and GET/POST /api/items plus GET/PATCH/DELETE /api/items/:id. Create returns 201, mutations return 200/204, invalid data 400, missing items 404. OPTIONS denies cross-origin use. Routes with unexpected query parameters are refused. A port of 0 chooses a local ephemeral port and prints the actual URL.

Offline unit tests run **real requests through an ephemeral local HTTP socket**, exercising create/list/detail/update/delete, missing IDs, invalid inputs, content type, oversized payloads, Host refusal, literal XSS content, browser assets and clean shutdown. This is a test/demo server with one connection at a time, no accounts, disk storage, TLS, multi-user support, production deployment or advanced browser assurance. Those must not be claimed until separately implemented and verified by #149/#153. No lease, merge permission or spending decision is made by this fixture.
