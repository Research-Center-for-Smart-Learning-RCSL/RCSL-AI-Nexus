# Deployment Topology

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md) and [security.md](./security.md). Describes which machine runs what, how traffic arrives, and what other people have to do.

## How this is arranged

**One file per numbered section, under [`deployment/`](./deployment/).** This
page is the index.

It was a single 82 KB file, and 40% of it was §9 alone. The unit is the
numbered section for the same reason it is in
[security.md](./security.md): the 62 references to this document from the
codebase and the docs are prose citations of a number — `deployment.md §9`,
`deployment.md section 10`, `deployment.md section 8.1` — and not one of them
depends on a heading anchor. §8.1 keeps its own file rather than folding into
§8, because it is cited by that number.

## Sections

**[1. Physical Components](./deployment/01-physical-components.md)**

**[2. Domains](./deployment/02-domains.md)**

**[3. Traffic Paths](./deployment/03-traffic-paths.md)**

**[4. The Critical Design Point: Separate Services, Not One Service With Two Ports](./deployment/04-separate-services-not-one-service.md)**

**[5. What the Proxy Administrator Needs to Do](./deployment/05-what-the-proxy-administrator-needs-to-do.md)**
- The one way this goes wrong, found on the first real attempt
- nginx configuration

**[6. What Is Lost Without a CDN, and Who Covers It](./deployment/06-what-is-lost-without-a-cdn-and-who-covers-it.md)**

**[7. Resolving the Real Client Address](./deployment/07-resolving-the-real-client-address.md)**

**[8. Migration Path](./deployment/08-migration-path.md)**

**[8.1 Source Availability Obligation](./deployment/08.1-source-availability-obligation.md)**

**[9. Build, Deploy, and Upgrade](./deployment/09-build-deploy-and-upgrade.md)**

**[10. Configuration and Secrets](./deployment/10-configuration-and-secrets.md)**

**[11. Local Development](./deployment/11-local-development.md)**
