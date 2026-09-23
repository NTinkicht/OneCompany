# Validate a saved Product Brief

Use `python onecompany.py journey --brief <draft.json> --target <target> --repository <owner/repo> --json` to revalidate a saved Product Brief against current read-only discovery. A valid complete draft reports `PROPOSAL_READY_NOT_APPROVED`; stale, malformed, authority-bearing, symlinked, oversized, or incomplete drafts are refused or remain incomplete. Validation is read-only and never grants approval, a lease, a RunKey, implementation authority, deployment authority, or extra provider spend.
