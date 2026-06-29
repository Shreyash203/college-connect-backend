# Secrets Usage Map

Repository: `Shreyash203/college-connect-backend`  
Environment: `dev`

## 1) GitHub repository secrets (Actions)
Used during CI/CD workflow execution.

- `AZURE_CREDENTIALS`
  - Purpose: Authenticate GitHub Actions to Azure (`azure/login`).
  - Used in: deployment workflow under `.github/workflows/`.

- `GHCR_PAT`
  - Purpose: Authenticate image operations with GitHub Container Registry (`ghcr.io`) when needed.
  - Used in: workflow steps for Docker registry login/push/pull integration.

## 2) Azure Key Vault secrets
Stored in `kv-college-connect-dev`.

- `mysql-host`
- `mysql-port`
- `mysql-db`
- `mysql-user`
- `mysql-password`

Purpose: centralized secret storage and rotation without hardcoding credentials in repository code.

## 3) Azure Container App secret references
Container App: `ca-college-connect-api`

Secret bindings reference Key Vault values:
- `mysql-host=keyvaultref:https://kv-college-connect-dev.vault.azure.net/secrets/mysql-host,identityref:system`
- `mysql-port=keyvaultref:https://kv-college-connect-dev.vault.azure.net/secrets/mysql-port,identityref:system`
- `mysql-db=keyvaultref:https://kv-college-connect-dev.vault.azure.net/secrets/mysql-db,identityref:system`
- `mysql-user=keyvaultref:https://kv-college-connect-dev.vault.azure.net/secrets/mysql-user,identityref:system`
- `mysql-password=keyvaultref:https://kv-college-connect-dev.vault.azure.net/secrets/mysql-password,identityref:system`

Runtime env mapping:
- `MYSQL_HOST=secretref:mysql-host`
- `MYSQL_PORT=secretref:mysql-port`
- `MYSQL_DB=secretref:mysql-db`
- `MYSQL_USER=secretref:mysql-user`
- `MYSQL_PASSWORD=secretref:mysql-password`

## 4) Backend usage at runtime
Backend reads environment variables (`MYSQL_*`) from Container App configuration.

Flow:
1. Secret value stored in Key Vault
2. Container App secret references Key Vault
3. Env var maps to Container App secret ref
4. Backend config reads env var and initializes DB connection

## 5) Important security note
- Do not commit plaintext secrets/tokens/passwords in code, docs, or workflow YAML.
- Rotate secrets immediately if accidentally exposed in terminal/chat history.
