# Secrets

One file per credential, mounted into containers at `/run/secrets/<name>` and
read there rather than passed as environment variables, because a value in
`environment` or an `env_file` is visible in `docker inspect` and in the process
list. The backend reads these through pydantic-settings `secrets_dir`; see
[docs/architecture/security.md](../docs/architecture/security.md) sections 6 and
8, and [deployment.md](../docs/architecture/deployment.md) section 10.

Only `*.example` and this file are tracked. The real files are git-ignored. Copy
each template, drop the `.example` suffix, and fill it in:

```sh
for f in secrets/*.example; do cp -n "$f" "${f%.example}"; done
```

**Write raw values with no trailing newline.** The file content *is* the secret.
On macOS, `printf '%s' 'value' > secrets/name` avoids the newline `echo` adds.

## The database accounts (security.md section 6)

Three Postgres accounts, not one. Each URL names its own account, and the
account name inside the URL is the single source of truth: the `migrate` job
reads the gateway and admin URLs to create those two roles and set their
passwords, then grants their privileges.

| File | Account | May do |
|---|---|---|
| `owner_database_url` | `nexus` (schema owner) | everything; used only by `migrate` |
| `gateway_database_url` | `nexus_gateway` | read every table, write only `usage_records` |
| `admin_database_url` | `nexus_admin` | full DML, no DDL |

Keep the usernames as above unless you change them in both the URLs and nowhere
else (the grants follow whatever username the URL carries). Each URL has the
shape `postgresql+asyncpg://<user>:<password>@postgres:5432/nexus`.

The account usernames and the database name (`POSTGRES_DB`) must be lower-case
`[a-z_][a-z0-9_]*`. The role provisioner (`db_roles.py`) constrains identifiers
to that shape and aborts on anything else, so a hyphen or a capital letter in a
name stops the `migrate` job rather than being silently quoted. Passwords have
no such restriction. If a password contains URL-reserved characters (`@`, `:`,
`/`, `#`), percent-encode it inside the URL; the value is decoded before use.

**`postgres_password` must equal the password inside `owner_database_url`.** The
Postgres container sets the `nexus` superuser password from `postgres_password`
on first initialisation; the owner URL then connects with it. They are two files
holding the same value because two different consumers read them (the Postgres
image, and the application).

The gateway and admin passwords appear only in their URLs. There is nowhere else
to keep them in step.

## Generating values

The four application secrets and the passwords are free-form high-entropy
strings. `TOTP_ENCRYPTION_KEY` is expanded with HKDF rather than stretched, so
it must be random, not chosen by a person (adapters/crypto/secret_box.py).

```sh
openssl rand -base64 32        # for each password and each of the four below
```

| File | Notes |
|---|---|
| `postgres_password` | also embed in `owner_database_url` |
| `redis_password` | Redis has no `_FILE` convention; the container reads this file in its command |
| `api_key_pepper` | rotating it needs `api_key_pepper_previous` set until keys are reissued |
| `totp_encryption_key` | rotating it makes every stored TOTP secret undecryptable; do not |
| `session_signing_key` | present for completeness; sessions are opaque Redis ids |
| `proxy_shared_secret` | must match the value the nginx proxy sends |
| `metrics_scrape_token` | bearer token for `/metrics`; the same file is mounted into Prometheus, so both sides use one value. Not needed if `METRICS_ENABLED=false` |
| `grafana_admin_password` | Grafana's initial admin password, replacing its `admin`/`admin` default |

`api_key_pepper_previous` is not shipped as a file because it is empty except
during a pepper rotation. Add it as a secret (and mount it into the backend
services) only for the duration of one.
