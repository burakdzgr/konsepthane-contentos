# Operations: secrets and sensitive configuration

The complete inventory of secret material ContentOS touches, how each
item is supplied and protected today, how to rotate it, and what MUST
change before any exposure beyond the single-operator deployment.
Docs-only; describes the system as built.

## Inventory

| Secret | Setting (env `CONTENTOS_*`) | Held as | Reaches |
| --- | --- | --- | --- |
| PostgreSQL URL (with password) | `DATABASE_URL` | `SecretStr` | backend + worker only |
| Redis broker/result URLs | `REDIS_BROKER_URL`, `REDIS_RESULT_URL` | `SecretStr` | backend + worker only |
| OpenAI API key | `OPENAI_API_KEY` | `SecretStr`, optional | worker provider adapters only, lazily |
| Publishing API key | `PUBLISHING_API_KEY` | `SecretStr`, default-None | the HTTP transport only; ISSUED by the operator and held ONLY in the gitignored `.env` (the compose whitelist passes it through; `.env.example` carries an empty placeholder). Rotation: change both sides' env values and recreate the Konsepthane api + ContentOS worker containers |
| User passwords | — (CLI env `CONTENTOS_NEW_PASSWORD` or prompt) | argon2id hash at rest | never argv, never logged, never stored raw |
| Session tokens | — | sha256 `token_hash` at rest | the raw token exists once in the login response and then only in the admin's HttpOnly `contentos_session` cookie |
| Admin → backend internal URL | admin `CONTENTOS_INTERNAL_API_URL` | server env | admin server side only; leak-tested never to render |

## Protections as built (with the tests that hold them)

- Settings use Pydantic `SecretStr`: reprs/logs never carry values
  (`test_database_url_secret_is_not_exposed_by_settings`).
- Provider adapters are constructed lazily and translate SDK failures
  into sanitized error classes — no keys, URLs, bodies, or traces in
  durable rows (`ai/providers/*`, attempt-metadata tests).
- The admin reduces every backend failure to bounded result kinds; the
  internal URL and transport details never reach the browser
  (leak assertions across the page/API tests, `smoke.ps1`).
- Auth: argon2id hashes, opaque sessions hashed at rest,
  indistinguishable login/session failures, HttpOnly SameSite=Lax
  cookie (Secure in production), token forwarded server-side only
  (`test_auth.py`, admin auth tests).
- Migrations/offline SQL never embed credentials
  (`test_alembic_ini_contains_no_credentials_or_urls`,
  `test_offline_upgrade_enables_pgvector_without_leaking_url`).
- No Konsepthane production credentials exist anywhere in this
  repository or its configuration, by design.

## Supply today

Docker Compose environment variables (see `docker-compose.yml` /
`.env.example`). This is acceptable ONLY for the single-operator
internal deployment: env vars are visible to anyone with host access.

## Rotation procedures

- **User passwords**: `uv run python -m contentos.auth.cli
  set-password <username> --reason "..."` (audited; old sessions stay
  valid until expiry — revoke by `set-active false/true` or wait out
  the fixed TTL). Session hygiene: `prune-sessions --retention-days N`.
- **OpenAI / Publishing keys**: change the env value and restart the
  worker (adapters are constructed per use; no cached clients survive
  a restart). Nothing durable references key material, so rotation
  needs no data migration.
- **Database/Redis passwords**: rotate on the service side, update the
  URLs, restart backend + worker. Sessions and all durable state are
  unaffected.

## Required before wider exposure (documented acceptances)

These are ACCEPTED gaps for the current single-tenant internal tool
and BLOCKERS for anything beyond it:

1. **A real secret store** (or at minimum docker secrets/sops) instead
   of plain compose env vars.
2. **TLS termination** in front of the admin and API (the session
   cookie is Secure-flagged in production settings but the deployment
   must actually serve HTTPS).
3. **Login rate-limiting/lockout** (deliberately absent; argon2id
   slows brute force but does not bound it).
4. **Publishing API key issuance/rotation ownership** — part of the
   open Publishing integration inputs (contract, auth method,
   production owner) tracked in `docs/memory/CURRENT_STATE.md`.
