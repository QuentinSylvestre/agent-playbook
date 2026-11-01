# Security policy

agent-playbook's skills instruct AI agents that run shell commands, edit files and push to git
on your machine. A flaw in a rule or a guard script can therefore matter more than its size suggests.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository page). Include what an agent could be led
to do, the files involved, and a reproduction if you have one. You will get an acknowledgement
within a week.

In scope:

- A governance rule or skill step that leads an agent to an unsafe action without the user's
  approval, such as destructive git commands, pushing secrets, or running downloaded code.
- A guard script that can be bypassed: a memory or governance write outside its allowlist, a
  credential that slips past the commit scan, a link that escapes the store repo.
- A setup path that overwrites or deletes user files without asking.

## Handling secrets

The playbook never needs your credentials. Seeds such as Kiro's `mcp.json` are written only when
absent, and are never overwritten. Keep tokens in your provider's own secret storage or
environment, never in this repo or your store repo. CI scans every pull request for
credential-shaped strings and personal paths.
