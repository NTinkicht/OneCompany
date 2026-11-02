# Install the OneCompany skill

1. `git clone https://github.com/NTinkicht/OneCompany.git`
2. `cd OneCompany`
3. Copy the skill folder into your Claude Code skills directory: `mkdir -p ~/.claude/skills && cp -r skills/onecompany ~/.claude/skills/`
4. Start Claude Code in the checkout and ask: "Use the onecompany skill to turn my idea into a company."
5. For other agents see `docs/agent-setup/onecompany-skill.md`.

The skill never approves for you, never asks for secrets, keeps autonomy at L1 and proposes no paid services.
A packaged Claude Code plugin manifest is intentionally not included yet: it must be verified against the current plugin documentation first.
