# Deployment Command History (Sanitized)

Date: 2026-06-29
Repository: `Shreyash203/college-connect-backend`
Branch: `dev`

> This log captures the command patterns used during setup and verification. Sensitive values are redacted.

## 1) Trigger / re-trigger CI workflow

```bash
git add .
git commit -m "ci: add backend dev deploy workflow"
git push origin dev
```

```bash
git commit --allow-empty -m "chore: retrigger dev deploy"
git push origin dev
```

## 2) MySQL Flexible Server provisioning (dev)

```bash
RG="rg-college-connect-dev"
LOC="centralindia"
MYSQL_SERVER="mysql-college-connect-dev"
DB_NAME="college_connect"
DB_ADMIN="ccadmin"
DB_PASS='<REDACTED>'
KV="kv-college-connect-dev"
APP="ca-college-connect-api"
```

```bash
az mysql flexible-server create \
  --resource-group $RG \
  --name $MYSQL_SERVER \
  --location $LOC \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --admin-user $DB_ADMIN \
  --admin-password "$DB_PASS" \
  --version 8.0.21 \
  --public-access 0.0.0.0
```

```bash
az mysql flexible-server db create \
  --resource-group $RG \
  --server-name $MYSQL_SERVER \
  --database-name $DB_NAME
```

```bash
MYSQL_HOST=$(az mysql flexible-server show -g $RG -n $MYSQL_SERVER --query fullyQualifiedDomainName -o tsv)
echo "MYSQL_HOST=$MYSQL_HOST"
```

## 3) Key Vault secret updates

```bash
az keyvault secret set --vault-name $KV --name mysql-host --value "$MYSQL_HOST"
az keyvault secret set --vault-name $KV --name mysql-port --value "3306"
az keyvault secret set --vault-name $KV --name mysql-db --value "$DB_NAME"
az keyvault secret set --vault-name $KV --name mysql-user --value "$DB_ADMIN"
az keyvault secret set --vault-name $KV --name mysql-password --value "$DB_PASS"
```

## 4) Container App secret bindings and env mapping

```bash
az containerapp secret set \
  -n $APP \
  -g $RG \
  --secrets \
  mysql-host=keyvaultref:https://$KV.vault.azure.net/secrets/mysql-host,identityref:system \
  mysql-port=keyvaultref:https://$KV.vault.azure.net/secrets/mysql-port,identityref:system \
  mysql-db=keyvaultref:https://$KV.vault.azure.net/secrets/mysql-db,identityref:system \
  mysql-user=keyvaultref:https://$KV.vault.azure.net/secrets/mysql-user,identityref:system \
  mysql-password=keyvaultref:https://$KV.vault.azure.net/secrets/mysql-password,identityref:system
```

```bash
az containerapp update \
  -n $APP \
  -g $RG \
  --set-env-vars \
  MYSQL_HOST=secretref:mysql-host \
  MYSQL_PORT=secretref:mysql-port \
  MYSQL_DB=secretref:mysql-db \
  MYSQL_USER=secretref:mysql-user \
  MYSQL_PASSWORD=secretref:mysql-password
```

## 5) Revision refresh / restart workarounds

```bash
REV=$(az containerapp revision list \
  -n ca-college-connect-api \
  -g rg-college-connect-dev \
  --query "[?properties.active==\`true\`][0].name" -o tsv)

echo $REV
```

```bash
az containerapp revision restart \
  -n ca-college-connect-api \
  -g rg-college-connect-dev \
  --revision "$REV"
```

(If restart API returns Method Not Allowed)

```bash
az containerapp update \
  -n ca-college-connect-api \
  -g rg-college-connect-dev \
  --revision-suffix dbrefresh$(date +%H%M%S)
```

## 6) Logs and runtime verification

```bash
az containerapp logs show \
  -n ca-college-connect-api \
  -g rg-college-connect-dev \
  --tail 100
```

```bash
az containerapp logs show -n ca-college-connect-api -g rg-college-connect-dev --tail 200
```

## 7) App URL and API checks

```bash
FQDN=$(az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv)
echo "APP_URL=https://$FQDN"
```

```bash
BASE="https://ca-college-connect-api.agreeablepebble-a4512869.centralindia.azurecontainerapps.io"

curl -i "$BASE/"
curl -i "$BASE/healthz"
curl -i "$BASE/docs"
curl -i "$BASE/openapi.json"
```

## 8) End-to-end auth/profile test (live backend)

```bash
BASE="https://ca-college-connect-api.agreeablepebble-a4512869.centralindia.azurecontainerapps.io"
EMAIL="student@iith.ac.in"
PASS="Test@12345"

# Register
curl -i -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}"

# Login
LOGIN_JSON=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$EMAIL&password=$PASS")

echo "$LOGIN_JSON"
TOKEN=$(echo "$LOGIN_JSON" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))")
echo "TOKEN=$TOKEN"

# Public endpoint
curl -i "$BASE/api/profiles"

# Protected create
curl -i -X POST "$BASE/api/profiles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"IITH Student","department":"CSE","year":"3","bio":"Hello from IITH","interests":["python","ai"]}'

# Protected me
curl -i "$BASE/api/profiles/me" \
  -H "Authorization: Bearer $TOKEN"
```
