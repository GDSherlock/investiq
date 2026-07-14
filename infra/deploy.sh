#!/bin/bash
#
# InvestIQ — Azure Container Apps Deployment Script
# Deploys all required Azure resources per the LLD Module-to-Azure mapping.
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
#   - Docker installed (for building container images)
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# Override defaults with environment variables:
#   RESOURCE_GROUP=mygroup LOCATION=eastus2 ./deploy.sh
#
# Skip to a specific step (1-11):
#   START_STEP=8 RESOURCE_GROUP=INVESTIQ POSTGRES_PASSWORD='...' ./deploy.sh

set -euo pipefail
export MSYS_NO_PATHCONV=1

START_STEP="${START_STEP:-1}"
step_active() { [ "$1" -ge "$START_STEP" ]; }

# ──────────────────────────────────────────────
# Configuration (override with env vars)
# ──────────────────────────────────────────────
PROJECT_NAME="${PROJECT_NAME:-investiqappnl}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-investiq}"
LOCATION="${LOCATION:-southeastasia}"
ENV_NAME="${ENV_NAME:-${PROJECT_NAME}-env}"
ACR_NAME="${ACR_NAME:-${PROJECT_NAME}acr}"
POSTGRES_SERVER="${POSTGRES_SERVER:-${PROJECT_NAME}-pgdb}"
POSTGRES_ADMIN="${POSTGRES_ADMIN:-projadmin}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -base64 16)}"
REDIS_NAME="${REDIS_NAME:-${PROJECT_NAME}-redis}"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-${PROJECT_NAME}storage}"
KEYVAULT_NAME="${KEYVAULT_NAME:-${PROJECT_NAME}-kv}"
LOG_ANALYTICS="${LOG_ANALYTICS:-${PROJECT_NAME}-logs}"
APPGW_NAME="${APPGW_NAME:-${PROJECT_NAME}-appgw}"
APPGW_VNET="${APPGW_VNET:-${PROJECT_NAME}-vnet}"
APPGW_SUBNET="${APPGW_SUBNET:-appgw-subnet}"
APPGW_PIP="${APPGW_PIP:-${PROJECT_NAME}-appgw-pip}"
AI_RESOURCE_NAME="${AI_RESOURCE_NAME:-${PROJECT_NAME}-ai}"
AI_HUB_NAME="${AI_HUB_NAME:-${PROJECT_NAME}-hub}"
AI_PROJECT_NAME="${AI_PROJECT_NAME:-${PROJECT_NAME}-project}"
GPT_DEPLOYMENT="${GPT_DEPLOYMENT:-gpt-5.4-mini}"
EMBEDDING_DEPLOYMENT="${EMBEDDING_DEPLOYMENT:-text-embedding-3-small}"

echo "============================================"
echo "InvestIQ Azure Deployment"
echo "Resource Group: $RESOURCE_GROUP"
echo "Location:       $LOCATION"
echo "============================================"

# ──────────────────────────────────────────────
# Recover variables from existing resources when skipping steps
# ──────────────────────────────────────────────
if ! step_active 1; then echo ">>> Skipping steps before ${START_STEP}..."; fi

if ! step_active 2; then
  LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS" --query customerId -o tsv)
  LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys --resource-group "$RESOURCE_GROUP" --workspace-name "$LOG_ANALYTICS" --query primarySharedKey -o tsv)
fi
if ! step_active 3; then
  ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
  ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)
fi
if ! step_active 5; then
  POSTGRES_FQDN=$(az postgres flexible-server show --resource-group "$RESOURCE_GROUP" --name "$POSTGRES_SERVER" --query fullyQualifiedDomainName -o tsv)
  DATABASE_URL="postgresql://${POSTGRES_ADMIN}:${POSTGRES_PASSWORD}@${POSTGRES_FQDN}:5432/investiqappnl?sslmode=require"
fi
if ! step_active 6; then
  REDIS_KEY=$(az redis list-keys --resource-group "$RESOURCE_GROUP" --name "$REDIS_NAME" --query primaryKey -o tsv)
  REDIS_HOST="${REDIS_NAME}.redis.cache.windows.net"
  REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"
fi
if ! step_active 9; then
  AI_ENDPOINT=$(az cognitiveservices account show --name "$AI_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query properties.endpoint -o tsv 2>/dev/null)
  AI_ENDPOINT="${AI_ENDPOINT%/}/openai/v1/"
  AI_KEY=$(az cognitiveservices account keys list --name "$AI_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --query key1 -o tsv 2>/dev/null)
fi

# ──────────────────────────────────────────────
# 1. Resource Group
# ──────────────────────────────────────────────
if step_active 1; then
echo ">>> Creating Resource Group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"
fi

# ──────────────────────────────────────────────
# 2. Log Analytics Workspace (M15: Observability)
# ──────────────────────────────────────────────
if step_active 2; then
echo ">>> Creating Log Analytics Workspace..."
az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --location "$LOCATION"

LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query customerId -o tsv)

LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$LOG_ANALYTICS" \
  --query primarySharedKey -o tsv)
fi

# ──────────────────────────────────────────────
# 3. Azure Container Registry
# ──────────────────────────────────────────────
if step_active 3; then
echo ">>> Creating Azure Container Registry..."
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --sku Standard \
  --admin-enabled true

ACR_LOGIN_SERVER=$(az acr show \
  --name "$ACR_NAME" \
  --query loginServer -o tsv)

ACR_PASSWORD=$(az acr credential show \
  --name "$ACR_NAME" \
  --query "passwords[0].value" -o tsv)

# Build and push container images
echo ">>> Building and pushing container images..."
az acr build \
  --registry "$ACR_NAME" \
  --image investiqappnl-api:latest \
  --file apps/api/Dockerfile .

az acr build \
  --registry "$ACR_NAME" \
  --image investiqappnl-ui:latest \
  --file apps/ui/Dockerfile .
fi

# ──────────────────────────────────────────────
# 4. Container Apps Environment (M1-M7 host)
# ──────────────────────────────────────────────
if step_active 4; then
echo ">>> Creating Container Apps Environment..."
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --logs-workspace-id "$LOG_ANALYTICS_ID" \
  --logs-workspace-key "$LOG_ANALYTICS_KEY"
fi

# ──────────────────────────────────────────────
# 5. Azure Database for PostgreSQL (M8)
# ──────────────────────────────────────────────
if step_active 5; then
echo ">>> Creating Azure Database for PostgreSQL Flexible Server..."
if az postgres flexible-server show --resource-group "$RESOURCE_GROUP" --name "$POSTGRES_SERVER" &>/dev/null; then
  echo "    PostgreSQL server '$POSTGRES_SERVER' already exists in '$RESOURCE_GROUP', skipping create."
else
  # Name may exist globally from a prior run in another RG — tolerate the error
  if ! az postgres flexible-server create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_SERVER" \
    --location "$LOCATION" \
    --admin-user "$POSTGRES_ADMIN" \
    --admin-password "$POSTGRES_PASSWORD" \
    --sku-name Standard_B1ms \
    --tier Burstable \
    --storage-size 32 \
    --version 16 \
    --yes; then
    echo "    WARN: Create failed — server name may already exist globally."
    echo "    Attempting to locate existing server..."
    # Check if it exists in current RG now (may have been created in a prior partial run)
    if ! az postgres flexible-server show --resource-group "$RESOURCE_GROUP" --name "$POSTGRES_SERVER" &>/dev/null; then
      echo "    ERROR: Server '$POSTGRES_SERVER' is taken globally but not in '$RESOURCE_GROUP'."
      echo "    Either delete the old server or set POSTGRES_SERVER to a unique name."
      exit 1
    fi
  fi
fi

# Create database (idempotent — ignores if exists)
az postgres flexible-server db create \
  --resource-group "$RESOURCE_GROUP" \
  --server-name "$POSTGRES_SERVER" \
  --database-name investiqappnl 2>/dev/null || true

# Allow all traffic (idempotent)
az postgres flexible-server firewall-rule create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_SERVER" \
  --rule-name AllowAll \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 255.255.255.255 2>/dev/null || true

POSTGRES_FQDN=$(az postgres flexible-server show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$POSTGRES_SERVER" \
  --query fullyQualifiedDomainName -o tsv)

DATABASE_URL="postgresql://${POSTGRES_ADMIN}:${POSTGRES_PASSWORD}@${POSTGRES_FQDN}:5432/investiqappnl?sslmode=require"

# Enable pgvector extension
echo ">>> Enabling pgvector extension..."
az extension add --name rdbms-connect --yes 2>/dev/null || true
az postgres flexible-server parameter set \
  --resource-group "$RESOURCE_GROUP" \
  --server-name "$POSTGRES_SERVER" \
  --name azure.extensions \
  --value vector

az postgres flexible-server execute \
  --name "$POSTGRES_SERVER" \
  --admin-user "$POSTGRES_ADMIN" \
  --admin-password "$POSTGRES_PASSWORD" \
  --database-name investiqappnl \
  --querytext "CREATE EXTENSION IF NOT EXISTS vector;"
fi

# ──────────────────────────────────────────────
# 6. Azure Cache for Redis (M9)
# ──────────────────────────────────────────────
if step_active 6; then
echo ">>> Creating Azure Cache for Redis..."
if az redis show --resource-group "$RESOURCE_GROUP" --name "$REDIS_NAME" &>/dev/null; then
  echo "    Redis '$REDIS_NAME' already exists, skipping create."
else
  az redis create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$REDIS_NAME" \
    --location "$LOCATION" \
    --sku Basic \
    --vm-size c0
fi

REDIS_KEY=$(az redis list-keys \
  --resource-group "$RESOURCE_GROUP" \
  --name "$REDIS_NAME" \
  --query primaryKey -o tsv)

REDIS_HOST="${REDIS_NAME}.redis.cache.windows.net"
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"
fi

# ──────────────────────────────────────────────
# 7. Azure Blob Storage (M10)
# ──────────────────────────────────────────────
if step_active 7; then
echo ">>> Creating Azure Blob Storage..."
if az storage account show --resource-group "$RESOURCE_GROUP" --name "$STORAGE_ACCOUNT" &>/dev/null; then
  echo "    Storage account '$STORAGE_ACCOUNT' already exists, skipping create."
else
  az storage account create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STORAGE_ACCOUNT" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2
fi

az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --name models \
  --auth-mode login 2>/dev/null || true

az storage container create \
  --account-name "$STORAGE_ACCOUNT" \
  --name reports \
  --auth-mode login 2>/dev/null || true
fi

# ──────────────────────────────────────────────
# 8. Azure Key Vault (M14)
# ──────────────────────────────────────────────
if step_active 8; then
echo ">>> Creating Azure Key Vault..."
if az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "    Key Vault '$KEYVAULT_NAME' already exists, skipping create."
else
  # Try to recover soft-deleted vault first, otherwise create new
  az keyvault create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$KEYVAULT_NAME" \
    --location "$LOCATION" \
    --enable-rbac-authorization
fi

# Assign Key Vault roles to current user
CURRENT_USER_ID=$(az ad signed-in-user show --query id -o tsv)
KV_RESOURCE_ID=$(az keyvault show --name "$KEYVAULT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)

az role assignment create \
  --assignee "$CURRENT_USER_ID" \
  --role "Key Vault Secrets Officer" \
  --scope "$KV_RESOURCE_ID" 2>/dev/null || true

az role assignment create \
  --assignee "$CURRENT_USER_ID" \
  --role "Key Vault Secrets User" \
  --scope "$KV_RESOURCE_ID" 2>/dev/null || true

# Store secrets (may need a few seconds for RBAC propagation)
echo ">>> Storing secrets in Key Vault..."
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" \
  --name "database-url" \
  --value "$DATABASE_URL" || echo "    WARN: Could not set database-url secret — RBAC may still be propagating."

az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" \
  --name "redis-url" \
  --value "$REDIS_URL" || echo "    WARN: Could not set redis-url secret — RBAC may still be propagating."
fi

# ──────────────────────────────────────────────
# 9. Azure AI Foundry (Hub + Project + Model Deployments)
# ──────────────────────────────────────────────
if step_active 9; then

echo ">>> Installing Azure ML CLI extension..."
az extension add --name ml --upgrade --yes 2>/dev/null || true

# 9a. Azure AI Services account (hosts model deployments)
echo ">>> Creating Azure AI Services account..."
if az cognitiveservices account show --name "$AI_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "    AI Services '$AI_RESOURCE_NAME' already exists, skipping create."
else
  az cognitiveservices account create \
    --name "$AI_RESOURCE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --kind AIServices \
    --sku S0 \
    --yes
fi

AI_ENDPOINT=$(az cognitiveservices account show \
  --name "$AI_RESOURCE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.endpoint -o tsv)
AI_ENDPOINT="${AI_ENDPOINT%/}/openai/v1/"

AI_KEY=$(az cognitiveservices account keys list \
  --name "$AI_RESOURCE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query key1 -o tsv)

AI_RESOURCE_ID=$(az cognitiveservices account show \
  --name "$AI_RESOURCE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query id -o tsv)

# 9b. Azure AI Foundry Hub
echo ">>> Creating Azure AI Foundry Hub..."
if az ml workspace show --name "$AI_HUB_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "    AI Hub '$AI_HUB_NAME' already exists, skipping create."
else
  az ml workspace create \
    --kind hub \
    --name "$AI_HUB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION"
fi

AI_HUB_ID=$(az ml workspace show \
  --name "$AI_HUB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query id -o tsv)

# 9c. Connect AI Services to Hub
echo ">>> Connecting AI Services to Foundry Hub..."
cat > /tmp/ai-connection.yml <<EOF
name: ${AI_RESOURCE_NAME}-connection
type: azure_ai_services
target: ${AI_RESOURCE_ID}
credentials:
  type: api_key
  key: ${AI_KEY}
EOF
az ml connection create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "$AI_HUB_NAME" \
  --file /tmp/ai-connection.yml 2>/dev/null || echo "    Connection may already exist, continuing."
rm -f /tmp/ai-connection.yml

# 9d. Azure AI Foundry Project
echo ">>> Creating Azure AI Foundry Project..."
if az ml workspace show --name "$AI_PROJECT_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "    AI Project '$AI_PROJECT_NAME' already exists, skipping create."
else
  az ml workspace create \
    --kind project \
    --name "$AI_PROJECT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --hub-id "$AI_HUB_ID"
fi

# 9e. Deploy GPT-5.4-mini (Responses API)
echo ">>> Deploying GPT-5.4-mini model..."
if az cognitiveservices account deployment show --name "$AI_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --deployment-name "$GPT_DEPLOYMENT" &>/dev/null; then
  echo "    Deployment '$GPT_DEPLOYMENT' already exists, skipping."
else
  az cognitiveservices account deployment create \
    --name "$AI_RESOURCE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$GPT_DEPLOYMENT" \
    --model-name gpt-5.4-mini \
    --model-version "2026-03-17" \
    --model-format OpenAI \
    --sku-capacity 30 \
    --sku-name GlobalStandard
fi

# 9f. Deploy text-embedding-3-small (Embeddings)
echo ">>> Deploying text-embedding-3-small model..."
if az cognitiveservices account deployment show --name "$AI_RESOURCE_NAME" --resource-group "$RESOURCE_GROUP" --deployment-name "$EMBEDDING_DEPLOYMENT" &>/dev/null; then
  echo "    Deployment '$EMBEDDING_DEPLOYMENT' already exists, skipping."
else
  az cognitiveservices account deployment create \
    --name "$AI_RESOURCE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$EMBEDDING_DEPLOYMENT" \
    --model-name text-embedding-3-small \
    --model-version "1" \
    --model-format OpenAI \
    --sku-capacity 30 \
    --sku-name Standard
fi

# Store AI credentials in Key Vault
echo ">>> Storing AI credentials in Key Vault..."
az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" \
  --name "ai-endpoint" \
  --value "$AI_ENDPOINT" 2>/dev/null || true

az keyvault secret set \
  --vault-name "$KEYVAULT_NAME" \
  --name "ai-key" \
  --value "$AI_KEY" \
  --output none 2>/dev/null || true

echo "    AI Endpoint:          ${AI_ENDPOINT}"
echo "    GPT Deployment:       ${GPT_DEPLOYMENT}"
echo "    Embedding Deployment: ${EMBEDDING_DEPLOYMENT}"
fi

# ──────────────────────────────────────────────
# 10. Deploy Container Apps
# ──────────────────────────────────────────────
if step_active 10; then

# M3: Backend API
echo ">>> Deploying Backend API Container App..."
az containerapp create \
  --name investiqappnl-api \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "${ACR_LOGIN_SERVER}/investiqappnl-api:latest" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_NAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8000 \
  --ingress internal \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
    "DATABASE_URL=$DATABASE_URL" \
    "USE_SQLITE=false" \
    "REDIS_URL=$REDIS_URL" \
    "UPLOAD_DIR=/app/uploads" \
    "AZURE_OPENAI_ENDPOINT=${AI_ENDPOINT}" \
    "AZURE_OPENAI_API_KEY=${AI_KEY}" \
    "AZURE_OPENAI_GPT_DEPLOYMENT=${GPT_DEPLOYMENT}" \
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=${EMBEDDING_DEPLOYMENT}"

API_FQDN=$(az containerapp show \
  --name investiqappnl-api \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

# M1: Web UI
echo ">>> Deploying Web UI Container App..."
az containerapp create \
  --name investiqappnl-ui \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "${ACR_LOGIN_SERVER}/investiqappnl-ui:latest" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_NAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 3000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --env-vars \
    "NEXT_PUBLIC_API_URL=https://${API_FQDN}"

UI_FQDN=$(az containerapp show \
  --name investiqappnl-ui \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

# M4: Orchestrator (IOE)
echo ">>> Deploying Orchestrator Container App..."
az containerapp create \
  --name investiqappnl-ioe \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "${ACR_LOGIN_SERVER}/investiqappnl-api:latest" \
  --registry-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_NAME" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8001 \
  --ingress internal \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
    "DATABASE_URL=$DATABASE_URL" \
    "REDIS_URL=$REDIS_URL" \
    "AZURE_OPENAI_ENDPOINT=${AI_ENDPOINT}" \
    "AZURE_OPENAI_API_KEY=${AI_KEY}" \
    "AZURE_OPENAI_GPT_DEPLOYMENT=${GPT_DEPLOYMENT}" \
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=${EMBEDDING_DEPLOYMENT}"

# M5: Agent Container Apps (8 agents)
AGENTS=("ingest" "sens" "mc" "cf" "debt" "monitor" "report" "assistant")

for AGENT in "${AGENTS[@]}"; do
  echo ">>> Deploying Agent: investiqappnl-agent-${AGENT}..."
  az containerapp create \
    --name "investiqappnl-agent-${AGENT}" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENV_NAME" \
    --image "${ACR_LOGIN_SERVER}/investiqappnl-api:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_NAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8000 \
    --ingress internal \
    --min-replicas 0 \
    --max-replicas 5 \
    --cpu 0.5 \
    --memory 1.0Gi \
    --env-vars \
      "DATABASE_URL=$DATABASE_URL" \
      "REDIS_URL=$REDIS_URL" \
      "AGENT_NAME=${AGENT}" \
      "AZURE_OPENAI_ENDPOINT=${AI_ENDPOINT}" \
      "AZURE_OPENAI_API_KEY=${AI_KEY}" \
      "AZURE_OPENAI_GPT_DEPLOYMENT=${GPT_DEPLOYMENT}" \
      "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=${EMBEDDING_DEPLOYMENT}"
done

# M7: Async Job Runner (Container Apps Jobs)
echo ">>> Creating Async Job Runner..."
if az containerapp job show --name investiqappnl-mc-job --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "    Job 'investiqappnl-mc-job' already exists, skipping create."
else
  az containerapp job create \
    --name investiqappnl-mc-job \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENV_NAME" \
    --image "${ACR_LOGIN_SERVER}/investiqappnl-api:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_NAME" \
    --registry-password "$ACR_PASSWORD" \
    --trigger-type Manual \
    --replica-timeout 3600 \
    --replica-retry-limit 0 \
    --cpu 2.0 \
    --memory 4.0Gi \
    --env-vars \
      "DATABASE_URL=$DATABASE_URL" \
      "REDIS_URL=$REDIS_URL"
fi
fi

# ──────────────────────────────────────────────
# 11. Application Gateway
# ──────────────────────────────────────────────
if step_active 11; then

# Retrieve Container App FQDNs
UI_FQDN=$(az containerapp show --name investiqappnl-ui --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)
API_FQDN=$(az containerapp show --name investiqappnl-api --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

# API must be externally reachable for AppGW to proxy to it
echo ">>> Switching API ingress to external for Application Gateway..."
az containerapp ingress enable \
  --name investiqappnl-api \
  --resource-group "$RESOURCE_GROUP" \
  --type external \
  --target-port 8000 2>/dev/null || true

API_FQDN=$(az containerapp show --name investiqappnl-api --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "    UI  backend: ${UI_FQDN}"
echo "    API backend: ${API_FQDN}"

# 11a. VNet + Subnet
echo ">>> Creating VNet for Application Gateway..."
if az network vnet show --resource-group "$RESOURCE_GROUP" --name "$APPGW_VNET" &>/dev/null; then
  echo "    VNet '$APPGW_VNET' already exists, skipping."
else
  az network vnet create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APPGW_VNET" \
    --address-prefix 10.0.0.0/16 \
    --subnet-name "$APPGW_SUBNET" \
    --subnet-prefix 10.0.0.0/24 \
    --location "$LOCATION"
fi

# 11b. Public IP (Standard SKU required for v2)
echo ">>> Creating Public IP for Application Gateway..."
if az network public-ip show --resource-group "$RESOURCE_GROUP" --name "$APPGW_PIP" &>/dev/null; then
  echo "    Public IP '$APPGW_PIP' already exists, skipping."
else
  az network public-ip create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APPGW_PIP" \
    --sku Standard \
    --allocation-method Static \
    --location "$LOCATION"
fi

# 11c. Application Gateway (Standard_v2)
echo ">>> Creating Application Gateway (this may take a few minutes)..."
if az network application-gateway show --resource-group "$RESOURCE_GROUP" --name "$APPGW_NAME" &>/dev/null; then
  echo "    Application Gateway '$APPGW_NAME' already exists, skipping create."
else
  az network application-gateway create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APPGW_NAME" \
    --location "$LOCATION" \
    --sku Standard_v2 \
    --capacity 1 \
    --vnet-name "$APPGW_VNET" \
    --subnet "$APPGW_SUBNET" \
    --public-ip-address "$APPGW_PIP" \
    --frontend-port 80 \
    --http-settings-port 443 \
    --http-settings-protocol Https \
    --servers "$UI_FQDN" \
    --priority 100
fi

# 11d. Configure default backend HTTP settings (UI)
echo ">>> Configuring backend HTTP settings..."
az network application-gateway http-settings update \
  --resource-group "$RESOURCE_GROUP" \
  --gateway-name "$APPGW_NAME" \
  --name appGatewayBackendHttpSettings \
  --port 443 \
  --protocol Https \
  --host-name-from-backend-pool true

# 11e. Health probe for UI
echo ">>> Creating health probes..."
if az network application-gateway probe show --resource-group "$RESOURCE_GROUP" --gateway-name "$APPGW_NAME" --name ui-probe &>/dev/null; then
  echo "    Probe 'ui-probe' already exists, skipping."
else
  az network application-gateway probe create \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name ui-probe \
    --protocol Https \
    --host-name-from-http-settings true \
    --path "/" \
    --interval 30 \
    --timeout 30 \
    --threshold 3
fi

# Associate probe with default HTTP settings
az network application-gateway http-settings update \
  --resource-group "$RESOURCE_GROUP" \
  --gateway-name "$APPGW_NAME" \
  --name appGatewayBackendHttpSettings \
  --probe ui-probe

# 11f. API backend pool
echo ">>> Adding API backend pool..."
if az network application-gateway address-pool show --resource-group "$RESOURCE_GROUP" --gateway-name "$APPGW_NAME" --name api-backend &>/dev/null; then
  echo "    Backend pool 'api-backend' already exists, updating..."
  az network application-gateway address-pool update \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name api-backend \
    --servers "$API_FQDN"
else
  az network application-gateway address-pool create \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name api-backend \
    --servers "$API_FQDN"
fi

# 11g. API HTTP settings (HTTPS, pick hostname from backend)
if az network application-gateway http-settings show --resource-group "$RESOURCE_GROUP" --gateway-name "$APPGW_NAME" --name api-https-settings &>/dev/null; then
  echo "    HTTP settings 'api-https-settings' already exists, skipping."
else
  az network application-gateway http-settings create \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name api-https-settings \
    --port 443 \
    --protocol Https \
    --host-name-from-backend-pool true
fi

# 11h. Health probe for API
if az network application-gateway probe show --resource-group "$RESOURCE_GROUP" --gateway-name "$APPGW_NAME" --name api-probe &>/dev/null; then
  echo "    Probe 'api-probe' already exists, skipping."
else
  az network application-gateway probe create \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name api-probe \
    --protocol Https \
    --host-name-from-http-settings true \
    --path "/docs" \
    --interval 30 \
    --timeout 30 \
    --threshold 3
fi

az network application-gateway http-settings update \
  --resource-group "$RESOURCE_GROUP" \
  --gateway-name "$APPGW_NAME" \
  --name api-https-settings \
  --probe api-probe

# 11i. Path-based routing: /api/* → API, default → UI
echo ">>> Configuring path-based routing..."
if az network application-gateway url-path-map show --resource-group "$RESOURCE_GROUP" --gateway-name "$APPGW_NAME" --name investiqappnl-routing &>/dev/null; then
  echo "    URL path map 'investiqappnl-routing' already exists, skipping."
else
  az network application-gateway url-path-map create \
    --resource-group "$RESOURCE_GROUP" \
    --gateway-name "$APPGW_NAME" \
    --name investiqappnl-routing \
    --default-address-pool appGatewayBackendPool \
    --default-http-settings appGatewayBackendHttpSettings \
    --paths "/api/*" \
    --address-pool api-backend \
    --http-settings api-https-settings \
    --rule-name api-path-rule
fi

# Update the default rule to use path-based routing
az network application-gateway rule update \
  --resource-group "$RESOURCE_GROUP" \
  --gateway-name "$APPGW_NAME" \
  --name rule1 \
  --rule-type PathBasedRouting \
  --url-path-map investiqappnl-routing \
  --priority 100

APPGW_PIP_ADDRESS=$(az network public-ip show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$APPGW_PIP" \
  --query ipAddress -o tsv)

echo ">>> Application Gateway deployed."
echo "    Public IP: ${APPGW_PIP_ADDRESS}"
echo "    URL:       http://${APPGW_PIP_ADDRESS}"
fi

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
echo ""
echo "============================================"
echo "DEPLOYMENT COMPLETE"
echo "============================================"
echo "UI URL:          https://${UI_FQDN:-N/A}"
echo "API (internal):  https://${API_FQDN:-N/A}"
echo "App Gateway:     http://${APPGW_PIP_ADDRESS:-N/A}"
echo "PostgreSQL:      ${POSTGRES_FQDN:-N/A}"
echo "Redis:           ${REDIS_HOST:-N/A}"
echo "Storage:         ${STORAGE_ACCOUNT}"
echo "Key Vault:       ${KEYVAULT_NAME}"
echo "AI Foundry Hub:  ${AI_HUB_NAME}"
echo "AI Project:      ${AI_PROJECT_NAME}"
echo "AI Endpoint:     ${AI_ENDPOINT:-N/A}"
echo "GPT Deployment:  ${GPT_DEPLOYMENT}"
echo "Embed Deployment:${EMBEDDING_DEPLOYMENT}"
echo ""
echo "IMPORTANT: Store these credentials securely:"
echo "  Postgres Password: ${POSTGRES_PASSWORD}"
echo "  Database URL:      ${DATABASE_URL}"
echo "  AI Key Loaded:     $([ -n "${AI_KEY:-}" ] && echo true || echo false)"
echo "============================================"
