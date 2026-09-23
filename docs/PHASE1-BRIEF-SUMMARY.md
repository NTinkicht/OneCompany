# Read a Product Brief safely

A saved Product Brief remains an owner draft, not execution authority. Run `python onecompany.py journey --brief <draft.json> --target <target> --repository <owner/repo>` for a concise status showing the current stage, missing owner answers, blockers, and next safe action. The command does not mutate the target, approve acceptance criteria, select an implementer, create a lease, deploy, or authorize spending.
