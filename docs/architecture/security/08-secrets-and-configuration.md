# 8. Secrets and Configuration

[← Security Architecture and Threat Model](../security.md)

- `.env` is never committed. `.gitignore` lists it explicitly, and `.env.example` carries field names only.
- **pre-commit plus gitleaks**, catching accidental secrets before they enter history. The cheapest high-return control here.
- Database passwords, the API key pepper, the TOTP encryption key, the session signing key, the metrics scrape token and the two Qdrant keys are **Docker secrets** (file mounts), not environment variables, because environment variables appear in `docker inspect` output and in the process list. **Built, on both sides**: `Settings` reads `/run/secrets` ([backend.md](../backend.md) §8) and `docker-compose.yml` carries a `secrets:` block mounting each service only what its role needs; `.env` holds non-secret configuration only. (This paragraph previously said the Compose half was outstanding. It was completed with the database account split and had not been updated here, which is the drift §13.0 exists to catch.)
- **Development and production secrets are never shared.** The Windows development machine uses values that cannot be mistaken for production ones.
- Pepper rotation invalidates every API key, so the verification path supports two peppers simultaneously to allow a staged rotation.
