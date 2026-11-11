---
name: Cybersecurity
description: Core cybersecurity practices for protecting systems, accounts, code, and networks.
---

# Cybersecurity

## Core principles
- **Least privilege:** grant only required access; remove unused accounts/keys/permissions.
- **Defense in depth:** use multiple layers (auth, network controls, patching, monitoring, backups).
- **Assume breach:** design to limit blast radius and detect/respond quickly.
- **Keep it updated:** patch OS, apps, dependencies, and firmware regularly.

## Account and identity security
1. Use strong, unique passwords (password manager) and enable **MFA** everywhere possible.
2. Prefer phishing-resistant MFA (passkeys/security keys) for critical accounts.
3. Review active sessions/tokens and revoke unused API keys or SSH keys.
4. Use separate admin and daily-use accounts where feasible.

## Device and system hardening
1. Enable automatic security updates; reboot/apply patches promptly.
2. Use disk encryption and screen lock; disable unnecessary services/ports.
3. Maintain a firewall (allow only needed inbound traffic) and secure remote access (SSH keys, no password auth if possible).
4. Install software from trusted sources; verify signatures/checksums when applicable.

## Secure coding and dependency hygiene
1. **Validate and sanitize input**; encode output to prevent injection/XSS.
2. Use parameterized queries/prepared statements for database access.
3. Never hardcode secrets; use environment variables/secret stores and rotate leaked credentials immediately.
4. Pin and audit dependencies (`pip/npm/etc.` audit tools), update vulnerable packages, and remove unused deps.
5. Handle errors safely (no sensitive data in logs/errors) and apply least-privilege service accounts.
6. Add tests for authz/authn boundaries and common abuse cases.

## Network and data protection
1. Use HTTPS/TLS for data in transit; avoid plaintext protocols.
2. Segment networks when possible; restrict lateral movement.
3. Encrypt sensitive data at rest; classify data and limit retention.
4. Maintain **tested backups** (3-2-1 rule) and verify restore procedures.

## Common threats to watch for
- **Phishing/social engineering:** verify sender/links/attachments; never approve unexpected MFA prompts.
- **Malware/ransomware:** keep backups offline/immutable where possible; limit execution privileges.
- **Credential stuffing:** unique passwords + MFA; monitor for breached credentials.
- **Misconfiguration/exposed services:** regularly review cloud/firewall/storage permissions.
- **Supply-chain/dependency attacks:** audit updates, lock versions, and review maintainer/source trust.

## Incident basics
1. Contain: isolate affected systems/accounts, revoke tokens/keys.
2. Eradicate and recover: remove malicious artifacts, patch root cause, restore from clean backups.
3. Review: document timeline/impact, improve detections and controls to prevent recurrence.
