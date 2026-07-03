# College Connect Backend

## Setup

1. Create a Python virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file from `.env.example` for local development, or export production environment variables.
4. Run the app:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## Azure SQL and Azure Key Vault

Use Azure SQL for the primary database connection and store secrets in Azure Key Vault for production safety.

1. Install the ODBC driver for SQL Server:
   - Windows: install Microsoft ODBC Driver 17 or 18 for SQL Server
   - Linux: install `msodbcsql17` and `unixodbc-dev`

2. Use one of these options:
   - Set `DATABASE_URL` and `JWT_SECRET_KEY` directly in environment variables or a local `.env` file.
   - Set `AZURE_KEY_VAULT_NAME` and store secrets in Azure Key Vault.

For Azure deployment, set `DATABASE_URL` to your Azure SQL connection string in Container Apps environment variables or Azure Key Vault rather than committing it to the repository.

3. Example Azure SQL connection string:
   ```text
   mssql+pyodbc://<username>:<password>@<server>.database.windows.net/<database>?driver=ODBC+Driver+17+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
   ```

4. Create Key Vault and set secrets:
   ```bash
   az login
   az keyvault create --name <vault-name> --resource-group <resource-group> --location <location>
   az keyvault secret set --vault-name <vault-name> --name DATABASE_URL --value "<connection-string>"
   az keyvault secret set --vault-name <vault-name> --name JWT_SECRET_KEY --value "<jwt-secret>"
   az keyvault secret set --vault-name <vault-name> --name ACCESS_TOKEN_EXPIRE_MINUTES --value "60"
   az keyvault secret set --vault-name <vault-name> --name AUTHORIZED_EMAIL_DOMAINS --value "iith.ac.in"
   ```

5. Configure runtime environment:
   - `AZURE_KEY_VAULT_NAME=<vault-name>`
   - Use Azure managed identity or `az login` locally so `DefaultAzureCredential` can access Key Vault.

## Notes
- Default local fallback remains SQLite at `backend.db` if `DATABASE_URL` is not provided.
- Do not commit `.env` or secrets to source control.
- Authorized email domains are configurable via `AUTHORIZED_EMAIL_DOMAINS`.
- Local Angular development uses `http://localhost:4200`, so set `CORS_ORIGINS` accordingly.
