# LBSNAA Form Builder — Azure Deployment Step-by-Step Guide

**Total estimated time: 4–5 working days** (comfortable pace, including testing)

---

## Phase 0 — Consolidate into one service
**Time: 3–4 hours**

Right now you're running two services on Railway (FormBuilder + DockerFaultyDocumentDetect). Your FormBuilder repo already has `validation_engine.py`, `model_manager.py`, `celebrity_detection.py`, and the `/api/validate/<doc_type>` endpoints built in. So you don't need the second service at all.

**What to do:**

- Open your FormBuilder's `app.py` and confirm the validate endpoints (`POST /api/validate/PHOTO`, `/ID`, `/LETTER`) are present and functional. They should be — the code is already there.
- If your FormBuilder is currently calling the DockerFaultyDocumentDetect service via HTTP (e.g., `requests.post("http://faulty-doc-service/api/validate/...")`), remove that call and route directly to the local `validation_engine.py` functions instead.
- Test locally: `docker compose up --build`, then hit `/health`, upload a test document through a form, and verify validation works end-to-end within the single container.
- Once confirmed, you only deploy **one** Docker image going forward. The DockerFaultyDocumentDetect repo becomes an archive.

---

## Phase 1 — Code changes before deploying
**Time: 1.5–2 days**

These are the code changes you make locally and test before touching Azure.

### Step 1.1 — Switch from SQLite to PostgreSQL
**Time: 3–4 hours**

Your `database.py` currently uses `sqlite3`. You need to swap it for PostgreSQL.

Install the dependency:
```
pip install psycopg2-binary
```

Add `psycopg2-binary` to your `requirements.txt`.

Update `database.py`. The schema stays almost identical — SQLite and PostgreSQL share most SQL syntax. The main changes are:

- Replace `sqlite3.connect(...)` with `psycopg2.connect(DATABASE_URL)`.
- Replace `INTEGER PRIMARY KEY AUTOINCREMENT` with `SERIAL PRIMARY KEY`.
- Replace `TEXT` (for JSON columns) with `JSONB` — this gives you queryable JSON in PostgreSQL.
- Replace `?` parameter placeholders with `%s`.
- Replace `datetime('now')` with `NOW()`.
- The unique index on `(course_id, email)` works the same way.

Read `DATABASE_URL` from an environment variable:
```python
import os
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/lbsnaa")
```

Test locally with a PostgreSQL container:
```
docker run -d --name pg-test -e POSTGRES_DB=lbsnaa -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=testpass -p 5432:5432 postgres:16
```

Run your app against it, create a course, submit a form, verify everything works.

### Step 1.2 — Move file uploads to Azure Blob Storage
**Time: 3–4 hours**

Install the Azure SDK:
```
pip install azure-storage-blob
```

Add `azure-storage-blob` to `requirements.txt`.

Update your `storage.py` (or create one if uploads are handled inline in `app.py`):

```python
import os
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta

BLOB_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER_NAME", "uploads")

def get_blob_client():
    return BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)

def upload_file(file_bytes, blob_name, content_type="application/octet-stream"):
    client = get_blob_client().get_blob_client(BLOB_CONTAINER, blob_name)
    client.upload_blob(file_bytes, content_type=content_type, overwrite=True)
    return blob_name

def get_download_url(blob_name, expiry_hours=1):
    # Generate a time-limited SAS URL for admin downloads
    account_name = get_blob_client().account_name
    account_key = get_blob_client().credential.account_key
    sas = generate_blob_sas(
        account_name=account_name,
        container_name=BLOB_CONTAINER,
        blob_name=blob_name,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
    )
    return f"https://{account_name}.blob.core.windows.net/{BLOB_CONTAINER}/{blob_name}?{sas}"
```

For the validation flow: when a participant uploads a document, you still need the file bytes in memory to run the ML validation — so the flow becomes: receive file → run validation in memory → if valid, upload to Blob Storage → store the blob name in PostgreSQL.

You don't need to store the ML model `.pkl` files in Blob Storage right away. Keep them baked into the Docker image for now (in the `models/` directory). This is simpler and the models don't change often. You can move them to Blob later when you need hot-swappable models (see the retraining section at the end).

### Step 1.3 — Update Dockerfile
**Time: 30 minutes**

Your existing Dockerfile is mostly fine. Just make sure:

```dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr poppler-utils libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["python", "app.py"]
```

Remove any `DATA_DIR` or SQLite-related volume logic from `docker-compose.yml` — you no longer need local file persistence.

### Step 1.4 — Test everything locally
**Time: 2–3 hours**

Create a local `docker-compose.yml` for testing:

```yaml
version: "3.8"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: lbsnaa
      POSTGRES_USER: admin
      POSTGRES_PASSWORD: testpass
    ports:
      - "5432:5432"

  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      DATABASE_URL: postgresql://admin:testpass@db:5432/lbsnaa
      ADMIN_PASSWORD: test123
      SECRET_KEY: dev-secret
      FLASK_ENV: development
      # For local testing, skip blob storage or use Azurite emulator
    depends_on:
      - db
```

Test the full flow: admin login → create course → open public form → fill fields → upload PHOTO/ID/LETTER → verify validation → submit → check admin dashboard → export CSV.

---

## Phase 2 — Azure infrastructure setup
**Time: 3–4 hours**

Now you set up Azure. Run these commands in order. Use PowerShell or Bash (Azure CLI works in both).

### Step 2.1 — Set variables

```powershell
$RG = "rg-lbsnaa-prod"
$LOCATION = "centralindia"
$ACR_NAME = "acrlbsnaa001"
$PLAN_NAME = "asp-lbsnaa-prod"
$APP_NAME = "lbsnaa-form-prod-001"
$IMAGE_NAME = "lbsnaa-form-builder"
$IMAGE_TAG = "v1"
$PG_SERVER = "pg-lbsnaa-prod"
$PG_ADMIN = "lbsnaaadmin"
$PG_PASSWORD = "<generate-a-strong-password>"   # use: openssl rand -base64 24
$STORAGE_ACCOUNT = "stlbsnaa001"
```

### Step 2.2 — Resource Group

```powershell
az group create --name $RG --location $LOCATION
```

### Step 2.3 — Azure Container Registry

```powershell
az acr create --resource-group $RG --name $ACR_NAME --sku Basic --admin-enabled false
```

### Step 2.4 — PostgreSQL Flexible Server

```powershell
az postgres flexible-server create \
  --resource-group $RG \
  --name $PG_SERVER \
  --location $LOCATION \
  --admin-user $PG_ADMIN \
  --admin-password $PG_PASSWORD \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0

# Create the database
az postgres flexible-server db create \
  --resource-group $RG \
  --server-name $PG_SERVER \
  --database-name lbsnaa
```

Note the connection string — you'll need it:
```
postgresql://<PG_ADMIN>:<PG_PASSWORD>@<PG_SERVER>.postgres.database.azure.com:5432/lbsnaa?sslmode=require
```

### Step 2.5 — Blob Storage Account

```powershell
az storage account create \
  --resource-group $RG \
  --name $STORAGE_ACCOUNT \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2

# Create the uploads container
az storage container create \
  --account-name $STORAGE_ACCOUNT \
  --name uploads \
  --auth-mode login

# Get the connection string (save this)
az storage account show-connection-string \
  --resource-group $RG \
  --name $STORAGE_ACCOUNT \
  --query connectionString -o tsv
```

### Step 2.6 — Build and push Docker image

```powershell
az acr build --registry $ACR_NAME --image "${IMAGE_NAME}:${IMAGE_TAG}" .
```

### Step 2.7 — App Service Plan + Web App

```powershell
az appservice plan create \
  --name $PLAN_NAME \
  --resource-group $RG \
  --is-linux \
  --sku P0V3

$ACR_LOGIN_SERVER = az acr show --resource-group $RG --name $ACR_NAME --query loginServer -o tsv

az webapp create \
  --resource-group $RG \
  --plan $PLAN_NAME \
  --name $APP_NAME \
  --deployment-container-image-name "${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"
```

### Step 2.8 — Managed identity for ACR pull

```powershell
$PRINCIPAL_ID = az webapp identity assign --resource-group $RG --name $APP_NAME --query principalId -o tsv
$ACR_ID = az acr show --resource-group $RG --name $ACR_NAME --query id -o tsv

az role assignment create --assignee $PRINCIPAL_ID --scope $ACR_ID --role AcrPull

az webapp config set --resource-group $RG --name $APP_NAME \
  --generic-configurations '{"acrUseManagedIdentityCreds": true}'
```

### Step 2.9 — Configure app settings

```powershell
az webapp config appsettings set --resource-group $RG --name $APP_NAME --settings \
  WEBSITES_PORT=5000 \
  PORT=5000 \
  FLASK_ENV=production \
  ADMIN_PASSWORD="<strong-admin-password>" \
  SECRET_KEY="<strong-random-secret>" \
  DATABASE_URL="postgresql://${PG_ADMIN}:${PG_PASSWORD}@${PG_SERVER}.postgres.database.azure.com:5432/lbsnaa?sslmode=require" \
  AZURE_STORAGE_CONNECTION_STRING="<paste-from-step-2.5>" \
  BLOB_CONTAINER_NAME=uploads
```

### Step 2.10 — Health check, Always On, logging, restart

```powershell
az webapp config set --resource-group $RG --name $APP_NAME \
  --health-check-path /health --always-on true

az webapp log config --name $APP_NAME --resource-group $RG \
  --docker-container-logging filesystem

az webapp restart --name $APP_NAME --resource-group $RG
```

### Step 2.11 — Verify

```powershell
$HOST = az webapp show --name $APP_NAME --resource-group $RG --query defaultHostName -o tsv
echo "Health: https://$HOST/health"
echo "Admin:  https://$HOST/admin/login"
```

Open both URLs. Verify `/health` returns `models_loaded: true`. Log in as admin, create a test course, submit a test form, verify validation and data persistence.

**Restart the app and check data is still there** — this confirms PostgreSQL is working (not ephemeral storage).

---

## Phase 3 — CI/CD with GitHub Actions
**Time: 2–3 hours**

### Step 3.1 — Create a service principal for GitHub

```powershell
$SUB_ID = az account show --query id -o tsv

az ad sp create-for-rbac --name "github-lbsnaa-deploy" \
  --role contributor \
  --scopes /subscriptions/$SUB_ID/resourceGroups/$RG \
  --sdk-auth
```

Copy the JSON output.

### Step 3.2 — Add GitHub secrets

In your FormBuilder repo, go to Settings → Secrets and variables → Actions. Add these secrets:

- `AZURE_CREDENTIALS` — paste the JSON from step 3.1
- `ACR_LOGIN_SERVER` — e.g. `acrlbsnaa001.azurecr.io`
- `ACR_NAME` — e.g. `acrlbsnaa001`
- `APP_NAME` — e.g. `lbsnaa-form-prod-001`
- `RESOURCE_GROUP` — e.g. `rg-lbsnaa-prod`

### Step 3.3 — Create the workflow file

Create `.github/workflows/deploy.yml` in your repo:

```yaml
name: Build and Deploy to Azure

on:
  push:
    branches: [master]
  workflow_dispatch:

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Azure Login
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Build image in ACR
        run: |
          az acr build \
            --registry ${{ secrets.ACR_NAME }} \
            --image lbsnaa-form-builder:${{ github.sha }} \
            --image lbsnaa-form-builder:latest \
            .

      - name: Deploy to App Service
        run: |
          az webapp config container set \
            --name ${{ secrets.APP_NAME }} \
            --resource-group ${{ secrets.RESOURCE_GROUP }} \
            --container-image-name ${{ secrets.ACR_LOGIN_SERVER }}/lbsnaa-form-builder:${{ github.sha }}

          az webapp restart \
            --name ${{ secrets.APP_NAME }} \
            --resource-group ${{ secrets.RESOURCE_GROUP }}

      - name: Wait and verify health
        run: |
          sleep 60
          HEALTH_URL="https://${{ secrets.APP_NAME }}.azurewebsites.net/health"
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)
          if [ "$STATUS" != "200" ]; then
            echo "Health check failed with status $STATUS"
            exit 1
          fi
          echo "Health check passed"
```

Now every push to `master` automatically builds, deploys, and verifies. No more manual `az acr build` commands.

---

## Phase 4 — Monitoring with Application Insights
**Time: 1–2 hours**

### Step 4.1 — Create Application Insights

```powershell
az monitor app-insights component create \
  --app "ai-lbsnaa-prod" \
  --location $LOCATION \
  --resource-group $RG \
  --kind web

$INSTRUMENTATION_KEY = az monitor app-insights component show \
  --app "ai-lbsnaa-prod" \
  --resource-group $RG \
  --query connectionString -o tsv
```

### Step 4.2 — Add to app settings

```powershell
az webapp config appsettings set --resource-group $RG --name $APP_NAME --settings \
  APPLICATIONINSIGHTS_CONNECTION_STRING="$INSTRUMENTATION_KEY"
```

### Step 4.3 — Add to your Flask app

```
pip install opencensus-ext-azure opencensus-ext-flask
```

In `app.py`, near the top:

```python
import os
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from opencensus.ext.azure.trace_exporter import AzureExporter
    from opencensus.ext.flask.flask_middleware import FlaskMiddleware
    from opencensus.trace.samplers import ProbabilitySampler

    FlaskMiddleware(
        app,
        exporter=AzureExporter(
            connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
        ),
        sampler=ProbabilitySampler(rate=1.0),
    )
```

This gives you request tracking, failure rates, response times, and exception logging in the Azure portal — all under the Application Insights blade.

### Step 4.4 — Set up an alert

In Azure Portal → Application Insights → Alerts → New alert rule:
- Condition: Health check failures > 2 in 5 minutes
- Action: Email notification to your team

---

## Phase 5 — Ongoing operations

### Deploying updates

After CI/CD is set up: just push to `master`. That's it. GitHub Actions handles the rest.

### Checking logs

```powershell
az webapp log tail --name $APP_NAME --resource-group $RG
```

### Database backup (automatic)

PostgreSQL Flexible Server gives you 7-day point-in-time restore out of the box. No configuration needed. To restore to a specific point:

```powershell
az postgres flexible-server restore \
  --resource-group $RG \
  --name pg-lbsnaa-restore \
  --source-server $PG_SERVER \
  --restore-point-in-time "2026-05-15T10:00:00Z"
```

### Updating app settings

```powershell
az webapp config appsettings set --resource-group $RG --name $APP_NAME --settings \
  SOME_NEW_SETTING="value"
```

App restarts automatically after settings change.

---

## Timeline summary

| Phase | What | Time |
|-------|------|------|
| Phase 0 | Consolidate repos, remove second service | 3–4 hours |
| Phase 1 | Code changes (PostgreSQL, Blob Storage, test) | 1.5–2 days |
| Phase 2 | Azure infra setup + first deploy | 3–4 hours |
| Phase 3 | GitHub Actions CI/CD | 2–3 hours |
| Phase 4 | Application Insights monitoring | 1–2 hours |
| **Total** | **End-to-end** | **4–5 working days** |

If you skip the PostgreSQL migration and stay on SQLite (not recommended), you can cut Phase 1 down to half a day and be deployed in 2–3 days. But you'd be trading long-term reliability for short-term speed.

---

## Monthly cost breakdown

| Resource | SKU | Monthly cost |
|----------|-----|-------------|
| App Service | P0v3 Linux | ~$60 |
| PostgreSQL Flexible Server | B1ms (1 vCore, 2GB) | ~$18 |
| Container Registry | Basic | ~$5 |
| Blob Storage | Standard LRS, <1GB | ~$0.50 |
| Application Insights | Free tier (<5GB) | ~$0 |
| Egress | <100GB (free tier) | $0 |
| **Total** | | **~$83–84/month** |

---

## Model retraining — is it complex?

**Short answer: No, it's straightforward.**

Your current ML pipeline uses scikit-learn models saved as `.pkl` files (`document_classifier.pkl`, `outlier_detector.pkl`, `feature_names.pkl`). The retraining workflow is:

**Step 1 — Retrain locally.** Gather your new training data (more document images). Run whatever training script you used originally (likely a Jupyter notebook or Python script that does feature extraction + `sklearn.fit()` + `joblib.dump()`). This produces new `.pkl` files.

**Step 2 — Replace the model files.** Drop the new `.pkl` files into the `models/` directory in your repo, replacing the old ones.

**Step 3 — Deploy.** Commit and push to `master`. GitHub Actions rebuilds the Docker image (which now contains the new models), pushes to ACR, and deploys. The `/health` endpoint confirms `models_loaded: true`. That's it.

**The whole retrain-to-deploy cycle takes about 30 minutes** (most of that being training time, which depends on your dataset size).

**Future improvement — hot-swappable models (optional, do later if needed):**

If you reach a point where you're retraining frequently and don't want to redeploy the whole container each time, you can move models to Blob Storage. The flow becomes: upload new `.pkl` files to Blob → call a `/admin/reload-models` endpoint you build → `model_manager.py` downloads from Blob and reloads in memory. No container restart needed. But this is over-engineering for now — the simple "replace files and redeploy" approach is perfectly fine at your scale and with CI/CD taking care of the deploy automatically.

**What if you want to switch from sklearn to a deep learning model?**

That's a bigger change but still manageable. You'd swap the sklearn classifier for something like a PyTorch or TensorFlow model, update `model_manager.py` to load it, and potentially bump up from P0v3 to a larger App Service SKU (or use Azure Container Apps with GPU if you need inference acceleration). But for document classification at your scale, sklearn is more than adequate — don't over-engineer this unless accuracy demands it.
