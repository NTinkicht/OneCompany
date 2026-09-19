# References and Provenance

OneCompany distinguishes source inspiration from implementation authority. External material can inspire a pattern; the local reviewed OneCompany contract governs behavior.

## Spotify engineering culture

Primary sources:

- Spotify Engineering, “Spotify engineering culture (part 1)” (2014): https://engineering.atspotify.com/2014/03/spotify-engineering-culture-part-1
- Spotify Engineering, “Spotify engineering culture (part 2)” (2014): https://engineering.atspotify.com/2014/9/spotify-engineering-culture-part-2

OneCompany adapts aligned autonomy and the squad/chapter/guild ideas. It does not claim the historical Spotify model is a current or prescriptive Spotify framework.

Related modern agent work (convergent evidence, not original OneCompany lineage):

- “1,500+ PRs Later: Spotify’s Journey with Our Background Coding Agent (Honk, Part 1)” (2025): https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1
- “Background Coding Agents: Context Engineering (Honk, Part 2)” (2025): https://www.engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2
- “Background Coding Agents: Predictable Results Through Strong Feedback Loops (Honk, Part 3)” (2025): https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3
- “Background Coding Agents: Supercharging Downstream Consumer Dataset Migrations (Honk, Part 4)” (2026): https://www.engineering.atspotify.com/2026/4/background-coding-agents-dataset-migrations-honk-part-4

## Specialist profiles and optional context tooling

- MIT-licensed upstream specialist profiles: https://github.com/msitarzewski/agency-agents
- Optional context-compression upstream: https://github.com/headroomlabs-ai/headroom

OneCompany maintains its own governance-scoped role overlays. Behavior-bearing
upstream components are opt-in and pinned where practical; an upstream library
does not grant worker capacity, identity, repository access or approval power.

## OpenAI scheduled and event-triggered tasks

Current product behavior should be re-checked before deployment because limits can change.

Official references:

- Scheduled tasks in ChatGPT: https://help.openai.com/en/articles/10291617
- ChatGPT Work and Codex: https://help.openai.com/en/articles/20001275/
- Connecting GitHub to ChatGPT: https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt-drease

At the time of the OneCompany 0.1.0 foundation audit (September 2026), the official documentation states that eligible paid plans can run recurring tasks up to hourly; Plus supports up to five active tasks; event-triggered Work tasks are available to eligible paid plans and can react to supported GitHub pull-request activity; connected-app permissions/approval requirements remain binding; tasks may pause; and tasks created in a ChatGPT Project should not be assumed to access files stored/uploaded in that Project.

OneCompany therefore treats external ChatGPT tasks as a liveness/supervision layer that must retrieve authoritative state from GitHub rather than from old chat/project context.

## GitHub Actions scheduling

Official references:

- Workflow syntax / `on.schedule`: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- Troubleshooting scheduled workflows: https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- Scheduled issue example / load-delay warning: https://docs.github.com/en/actions/tutorials/manage-your-work/schedule-issue-creation

GitHub documents scheduled workflows as default-branch workflows, with a minimum schedule interval of five minutes, and warns that scheduled runs can be delayed or dropped during high-load periods, especially around the start of an hour. OneCompany therefore schedules away from minute `00`, treats schedules as a reconciliation safety net rather than a correctness clock, and requires scheduler-health visibility.

## Attribution policy

When OneCompany incorporates substantive third-party code or text, preserve the applicable copyright/license notices. When it merely adapts an idea/pattern, document provenance here without implying endorsement or ownership by the source project.
