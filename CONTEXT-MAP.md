# Context Map

## Contexts

- [Hermes Repository](./docs/repository/CONTEXT.md): owns reviewed Hermes development sources without becoming a runtime or backup mirror.
- [Hermes Job Watcher](./CONTEXT.md): discovers and filters job postings for Discord delivery.
- [VPS Security Audit](./security-audit/CONTEXT.md): assesses VPS malware signals, remote-access posture, and exposure without remediation.
- [Yanto Persona / Voice](./docs/CONTEXT.md): defines the Hermes agent's user-facing voice.

## Relationships

- **Hermes Job Watcher -> Yanto Persona / Voice**: Job Watcher delivers notifications through the Hermes Discord bot, but its role and location policy are independent from conversational voice rules.
- **VPS Security Audit -> Yanto Persona / Voice**: Security Audit delivers deterministic findings through Hermes, but it does not authorize or perform remediation.
