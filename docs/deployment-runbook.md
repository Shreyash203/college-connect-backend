# Deployment Runbook (Step by Step)

Date completed: 2026-06-29  
Repository: `Shreyash203/college-connect-backend`  
Branch: `dev`

## Objective
Deploy backend to Azure Container Apps with CI/CD, connect MySQL, and validate live API end-to-end.

## Step 1 — CI/CD workflow and trigger
- Added backend deployment workflow for `dev` branch.
- Triggered workflow by pushing to `dev` (including empty commit when needed).
- Confirmed workflow run eventually succeeded.

## Step 2 — Provision database
- Created Azure Database for MySQL Flexible Server in `centralindia`.
- Created database `college_connect`.
- Retrieved server FQDN for application connection.

## Step 3 — Store DB config in Key Vault
- Updated Key Vault `kv-college-connect-dev` with:
  - `mysql-host`
  - `mysql-port`
  - `mysql-db`
  - `mysql-user`
  - `mysql-password`

## Step 4 — Wire Container App to Key Vault secrets
- Bound Container App secrets to Key Vault references with managed identity.
- Mapped runtime env vars (`MYSQL_*`) to those secret refs.

## Step 5 — Refresh revision
- Attempted revision restart; encountered CLI/API behavior requiring `--revision` and later Method Not Allowed.
- Used `az containerapp update --revision-suffix ...` to force a fresh revision and pick latest secret values.

## Step 6 — Validate runtime health
- Checked container logs and confirmed app startup:
  - Uvicorn started
  - `GET /` returned `200 OK`

## Step 7 — Discover actual API routes
- `GET /api/users` returned `404` (endpoint not defined).
- Inspected `/openapi.json` and confirmed available endpoints:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/profiles`
  - `POST /api/profiles`
  - `GET /api/profiles/me`

## Step 8 — End-to-end live backend test
- Initial register with non-college email rejected as expected.
- Re-tested with `@iith.ac.in` email:
  - Register: success
  - Login: success (JWT issued)
  - `GET /api/profiles`: success
  - `POST /api/profiles` (Bearer token): success with DB write
  - `GET /api/profiles/me`: initially 401 due to token header typo (`~`), fixed by sending exact Bearer token.

## Result
Deployment is successful and backend is live with working auth + DB operations.

## Known notes
- Public ingress is enabled; share link carefully.
- Before broad/public launch: tighten CORS, rate limits, observability, docs exposure, and rotate any temporary/test secrets.
