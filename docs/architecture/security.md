# Security Architecture and Threat Model

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md), [backend.md](./backend.md), [frontend.md](./frontend.md), and [deployment.md](./deployment.md).

## How this is arranged

**One file per numbered section, under [`security/`](./security/).** This page
is the index and holds no controls of its own.

It was a single 196 KB file. The unit is the numbered section because that is
the unit the rest of the repository already uses: there are 344 references to
this document across the codebase and the docs, and they are written as
`security.md §7.3` or `security.md section 9.4` — 438 of them naming a
top-level section and 698 naming a subsection of one. Not one of them depends
on a heading anchor, which is what makes the move safe. A reference's leading
number picks the file; the rest of it is a heading inside.

## Sections

**[0. What This System Actually Is](./security/00-what-this-system-actually-is.md)**

**[1. Core Principle: Separate the Control Plane From the Data Plane](./security/01-control-plane-vs-data-plane.md)**

**[2. Threat Model](./security/02-threat-model.md)**

**[3. Network Architecture](./security/03-network-architecture.md)**
- 3.1 Public Entrance: External openresty Reverse Proxy
- 3.2 Network Segmentation
- 3.3 Rule: No Port May Be Published on `0.0.0.0`
- 3.4 Tailscale ACL

**[4. Data Plane Hardening](./security/04-data-plane-hardening.md)**
- 4.1 Source Restriction
- 4.2 API Key Design
- 4.3 Resource Guardrails
- 4.4 General Public Service Hardening

**[5. Identity and Authorization](./security/05-identity-and-authorization.md)**
- 5.1 Management UI: Two Entrances, Two Authentication Schemes
- 5.2 Roles and Where Authorization Lives
- 5.3 Local Credentials, TOTP, and Sessions
- 5.4 Invitations and Password Reset
- 5.5 Bootstrapping the First Administrator

**[6. Service-to-Service Authentication: Do Not Trust the Internal Network](./security/06-service-to-service-authentication.md)**

**[7. High-Risk Features](./security/07-high-risk-features.md)**
- 7.1 Model Download and Load: The Highest-Risk Path in the System
- 7.2 Node Registration: SSRF
- 7.3 Knowledge Base (built, Phase 2)
- 7.4 Prompt Templates (built 2026-08-05)
- 7.5 The Management Assistant

**[8. Secrets and Configuration](./security/08-secrets-and-configuration.md)**

**[9. Data Protection and Logging Boundaries](./security/09-data-protection-and-logging-boundaries.md)**
- 9.1 Classification
- 9.2 Logging Boundaries
- 9.3 Encryption at Rest and the FileVault Tension
- 9.4 Backups
- 9.5 Refusals, and Why They Are Kept Where the Caller Can Read Them

**[10. Supply Chain](./security/10-supply-chain.md)**

**[11. Host Hardening (macOS)](./security/11-host-hardening.md)**

**[12. Audit Logging](./security/12-audit-logging.md)**
- 12.1 The Audit Log Is Deletable, and by Whom

**[13. Phased Rollout](./security/13-phased-rollout.md)**
- 13.0 What is actually implemented

**[14. Pre-Launch Checklist](./security/14-pre-launch-checklist.md)**

**[15. Accepted Risks](./security/15-accepted-risks.md)**
- 15.1 Inference Traffic Passes Through a Third-Party Machine in Plaintext
- 15.2 No Edge Protection
- 15.3 The Country Filter Is Bypassable
- 15.4 Wildcard DNS on a Shared Domain
- 15.5 The Gateway Reaching the Tailnet Admin Entrance — Resolved
- 15.6 FileVault Deferred Until the UPS Lands
- 15.7 The Alerting Credential Is the Operator's Own Mailbox
- 15.8 The Public Landing Page Shows an Admin API Error to an Anonymous Reader
