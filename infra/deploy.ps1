#
# InvestIQ — Azure Container Apps Deployment Script (PowerShell)
# Deploys all required Azure resources per the LLD Module-to-Azure mapping.
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
#   - Docker installed (for building container images)
#
# Usage:
#   .\deploy.ps1
#   .\deploy.ps1 -ResourceGroup "mygroup" -Location "eastus2"
#

param(
    [string]$ProjectName = "InvestIQAppNL",
    [string]$ResourceGroup = "rg-InvestIQ",
    [string]$Location = "southeastasia"
)

$ErrorActionPreference = "Stop"

$EnvName = "$ProjectName-env"
$AcrName = "${ProjectName}acr"
$PostgresServer = "$ProjectName-pgdb"
$PostgresAdmin = "projadmin"
$PostgresPassword = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
$RedisName = "$ProjectName-redis"
$StorageAccount = "${ProjectName}storage"
$KeyVaultName = "$ProjectName-kv"
$LogAnalytics = "$ProjectName-logs"
$AppgwName = "$ProjectName-appgw"
$AppgwVnet = "$ProjectName-vnet"
$AppgwSubnet = "appgw-subnet"
$AppgwPip = "$ProjectName-appgw-pip"
$AiResourceName = "$ProjectName-ai"
$AiHubName = "$ProjectName-hub"
$AiProjectName = "$ProjectName-project"
$GptDeployment = "gpt-5.4-mini"
$EmbeddingDeployment = "text-embedding-3-small"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "InvestIQ Azure Deployment" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup"
Write-Host "Location:       $Location"
Write-Host "============================================" -ForegroundColor Cyan

# 1. Resource Group
Write-Host ">>> Creating Resource Group..." -ForegroundColor Yellow
az group create --name $ResourceGroup --location $Location

# 2. Log Analytics Workspace (M15)
Write-Host ">>> Creating Log Analytics Workspace..." -ForegroundColor Yellow
az monitor log-analytics workspace create `
    --resource-group $ResourceGroup `
    --workspace-name $LogAnalytics `
    --location $Location

$LogAnalyticsId = az monitor log-analytics workspace show `
    --resource-group $ResourceGroup `
    --workspace-name $LogAnalytics `
    --query customerId -o tsv

$LogAnalyticsKey = az monitor log-analytics workspace get-shared-keys `
    --resource-group $ResourceGroup `
    --workspace-name $LogAnalytics `
    --query primarySharedKey -o tsv

# 3. Azure Container Registry
Write-Host ">>> Creating Azure Container Registry..." -ForegroundColor Yellow
az acr create `
    --resource-group $ResourceGroup `
    --name $AcrName `
    --sku Standard `
    --admin-enabled true

$AcrLoginServer = az acr show --name $AcrName --query loginServer -o tsv
$AcrPassword = az acr credential show --name $AcrName --query "passwords[0].value" -o tsv

# Build and push images
Write-Host ">>> Building and pushing container images..." -ForegroundColor Yellow
az acr build --registry $AcrName --image InvestIQAppNL-api:latest --file apps/api/Dockerfile .
az acr build --registry $AcrName --image InvestIQAppNL-ui:latest --file apps/ui/Dockerfile .

# 4. Container Apps Environment
Write-Host ">>> Creating Container Apps Environment..." -ForegroundColor Yellow
az containerapp env create `
    --name $EnvName `
    --resource-group $ResourceGroup `
    --location $Location `
    --logs-workspace-id $LogAnalyticsId `
    --logs-workspace-key $LogAnalyticsKey

# 5. PostgreSQL Flexible Server (M8)
Write-Host ">>> Creating PostgreSQL Flexible Server..." -ForegroundColor Yellow
az postgres flexible-server create `
    --resource-group $ResourceGroup `
    --name $PostgresServer `
    --location $Location `
    --admin-user $PostgresAdmin `
    --admin-password $PostgresPassword `
    --sku-name Standard_B1ms `
    --tier Burstable `
    --storage-size 32 `
    --version 16 `
    --yes

az postgres flexible-server db create `
    --resource-group $ResourceGroup `
    --server-name $PostgresServer `
    --database-name InvestIQAppNL

az postgres flexible-server firewall-rule create `
    --resource-group $ResourceGroup `
    --name $PostgresServer `
    --rule-name AllowAll `
    --start-ip-address 0.0.0.0 `
    --end-ip-address 255.255.255.255

$PostgresFqdn = az postgres flexible-server show `
    --resource-group $ResourceGroup `
    --name $PostgresServer `
    --query fullyQualifiedDomainName -o tsv

$DatabaseUrl = "postgresql://${PostgresAdmin}:${PostgresPassword}@${PostgresFqdn}:5432/InvestIQAppNL?sslmode=require"

# Enable pgvector extension
Write-Host ">>> Enabling pgvector extension..." -ForegroundColor Yellow
az extension add --name rdbms-connect --yes 2>$null
az postgres flexible-server parameter set `
    --resource-group $ResourceGroup `
    --server-name $PostgresServer `
    --name azure.extensions `
    --value vector

az postgres flexible-server execute `
    --name $PostgresServer `
    --admin-user $PostgresAdmin `
    --admin-password $PostgresPassword `
    --database-name InvestIQAppNL `
    --querytext "CREATE EXTENSION IF NOT EXISTS vector;"

# 6. Azure Cache for Redis (M9)
Write-Host ">>> Creating Azure Cache for Redis..." -ForegroundColor Yellow
az redis create `
    --resource-group $ResourceGroup `
    --name $RedisName `
    --location $Location `
    --sku Basic `
    --vm-size c0

$RedisKey = az redis list-keys --resource-group $ResourceGroup --name $RedisName --query primaryKey -o tsv
$RedisHost = "$RedisName.redis.cache.windows.net"
$RedisUrl = "rediss://:${RedisKey}@${RedisHost}:6380/0"

# 7. Azure Blob Storage (M10)
Write-Host ">>> Creating Azure Blob Storage..." -ForegroundColor Yellow
az storage account create `
    --resource-group $ResourceGroup `
    --name $StorageAccount `
    --location $Location `
    --sku Standard_LRS `
    --kind StorageV2

az storage container create --account-name $StorageAccount --name models --auth-mode login
az storage container create --account-name $StorageAccount --name reports --auth-mode login

# 8. Azure Key Vault (M14)
Write-Host ">>> Creating Azure Key Vault..." -ForegroundColor Yellow
az keyvault create `
    --resource-group $ResourceGroup `
    --name $KeyVaultName `
    --location $Location `
    --enable-rbac-authorization

# Assign Key Vault roles to current user
$CurrentUserId = az ad signed-in-user show --query id -o tsv
$KvResourceId = az keyvault show --name $KeyVaultName --resource-group $ResourceGroup --query id -o tsv

az role assignment create `
    --assignee $CurrentUserId `
    --role "Key Vault Secrets Officer" `
    --scope $KvResourceId 2>$null

az role assignment create `
    --assignee $CurrentUserId `
    --role "Key Vault Secrets User" `
    --scope $KvResourceId 2>$null

az keyvault secret set --vault-name $KeyVaultName --name "database-url" --value $DatabaseUrl
az keyvault secret set --vault-name $KeyVaultName --name "redis-url" --value $RedisUrl

# 9. Azure AI Foundry (Hub + Project + Model Deployments)
Write-Host ">>> Installing Azure ML CLI extension..." -ForegroundColor Yellow
az extension add --name ml --upgrade --yes 2>$null

# 9a. Azure AI Services account
Write-Host ">>> Creating Azure AI Services account..." -ForegroundColor Yellow
az cognitiveservices account create `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --location $Location `
    --kind AIServices `
    --sku S0 `
    --yes

$AiEndpoint = az cognitiveservices account show `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --query properties.endpoint -o tsv
$AiEndpoint = $AiEndpoint.TrimEnd("/") + "/openai/v1/"

$AiKey = az cognitiveservices account keys list `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --query key1 -o tsv

$AiResourceId = az cognitiveservices account show `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --query id -o tsv

# 9b. Azure AI Foundry Hub
Write-Host ">>> Creating Azure AI Foundry Hub..." -ForegroundColor Yellow
az ml workspace create `
    --kind hub `
    --name $AiHubName `
    --resource-group $ResourceGroup `
    --location $Location

$AiHubId = az ml workspace show `
    --name $AiHubName `
    --resource-group $ResourceGroup `
    --query id -o tsv

# 9c. Connect AI Services to Hub
Write-Host ">>> Connecting AI Services to Foundry Hub..." -ForegroundColor Yellow
$connectionYaml = @"
name: $AiResourceName-connection
type: azure_ai_services
target: $AiResourceId
credentials:
  type: api_key
  key: $AiKey
"@
$connectionFile = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.yml'
$connectionYaml | Set-Content -Path $connectionFile -Encoding UTF8
az ml connection create `
    --resource-group $ResourceGroup `
    --workspace-name $AiHubName `
    --file $connectionFile 2>$null
Remove-Item -Path $connectionFile -ErrorAction SilentlyContinue

# 9d. Azure AI Foundry Project
Write-Host ">>> Creating Azure AI Foundry Project..." -ForegroundColor Yellow
az ml workspace create `
    --kind project `
    --name $AiProjectName `
    --resource-group $ResourceGroup `
    --hub-id $AiHubId

# 9e. Deploy GPT-5.4-mini (Responses API)
Write-Host ">>> Deploying GPT-5.4-mini model..." -ForegroundColor Yellow
az cognitiveservices account deployment create `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --deployment-name $GptDeployment `
    --model-name gpt-5.4-mini `
    --model-version "2026-03-17" `
    --model-format OpenAI `
    --sku-capacity 30 `
    --sku-name GlobalStandard

# 9f. Deploy text-embedding-3-small (Embeddings)
Write-Host ">>> Deploying text-embedding-3-small model..." -ForegroundColor Yellow
az cognitiveservices account deployment create `
    --name $AiResourceName `
    --resource-group $ResourceGroup `
    --deployment-name $EmbeddingDeployment `
    --model-name text-embedding-3-small `
    --model-version "1" `
    --model-format OpenAI `
    --sku-capacity 30 `
    --sku-name Standard

# Store AI credentials in Key Vault
Write-Host ">>> Storing AI credentials in Key Vault..." -ForegroundColor Yellow
az keyvault secret set --vault-name $KeyVaultName --name "ai-endpoint" --value $AiEndpoint 2>$null
az keyvault secret set --vault-name $KeyVaultName --name "ai-key" --value $AiKey --output none 2>$null

Write-Host "    AI Endpoint:          $AiEndpoint"
Write-Host "    GPT Deployment:       $GptDeployment"
Write-Host "    Embedding Deployment: $EmbeddingDeployment"

# 10. Deploy Container Apps

# M3: Backend API
Write-Host ">>> Deploying Backend API..." -ForegroundColor Yellow
az containerapp create `
    --name InvestIQAppNL-api `
    --resource-group $ResourceGroup `
    --environment $EnvName `
    --image "$AcrLoginServer/InvestIQAppNL-api:latest" `
    --registry-server $AcrLoginServer `
    --registry-username $AcrName `
    --registry-password $AcrPassword `
    --target-port 8000 `
    --ingress internal `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars "DATABASE_URL=$DatabaseUrl" "USE_SQLITE=false" "REDIS_URL=$RedisUrl" "UPLOAD_DIR=/app/uploads" "AZURE_OPENAI_ENDPOINT=$AiEndpoint" "AZURE_OPENAI_API_KEY=$AiKey" "AZURE_OPENAI_GPT_DEPLOYMENT=$GptDeployment" "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$EmbeddingDeployment"

$ApiFqdn = az containerapp show `
    --name InvestIQAppNL-api `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

# M1: Web UI
Write-Host ">>> Deploying Web UI..." -ForegroundColor Yellow
az containerapp create `
    --name InvestIQAppNL-ui `
    --resource-group $ResourceGroup `
    --environment $EnvName `
    --image "$AcrLoginServer/InvestIQAppNL-ui:latest" `
    --registry-server $AcrLoginServer `
    --registry-username $AcrName `
    --registry-password $AcrPassword `
    --target-port 3000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 3 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --env-vars "NEXT_PUBLIC_API_URL=https://$ApiFqdn"

$UiFqdn = az containerapp show `
    --name InvestIQAppNL-ui `
    --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

# M4: Orchestrator
Write-Host ">>> Deploying Orchestrator..." -ForegroundColor Yellow
az containerapp create `
    --name InvestIQAppNL-ioe `
    --resource-group $ResourceGroup `
    --environment $EnvName `
    --image "$AcrLoginServer/InvestIQAppNL-api:latest" `
    --registry-server $AcrLoginServer `
    --registry-username $AcrName `
    --registry-password $AcrPassword `
    --target-port 8001 `
    --ingress internal `
    --min-replicas 1 `
    --max-replicas 3 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars "DATABASE_URL=$DatabaseUrl" "REDIS_URL=$RedisUrl" "AZURE_OPENAI_ENDPOINT=$AiEndpoint" "AZURE_OPENAI_API_KEY=$AiKey" "AZURE_OPENAI_GPT_DEPLOYMENT=$GptDeployment" "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$EmbeddingDeployment"

# M5: Agent Container Apps
$Agents = @("ingest", "sens", "mc", "cf", "debt", "report", "assistant")

foreach ($Agent in $Agents) {
    Write-Host ">>> Deploying Agent: InvestIQAppNL-agent-$Agent..." -ForegroundColor Yellow
    az containerapp create `
        --name "InvestIQAppNL-agent-$Agent" `
        --resource-group $ResourceGroup `
        --environment $EnvName `
        --image "$AcrLoginServer/InvestIQAppNL-api:latest" `
        --registry-server $AcrLoginServer `
        --registry-username $AcrName `
        --registry-password $AcrPassword `
        --target-port 8000 `
        --ingress internal `
        --min-replicas 0 `
        --max-replicas 5 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --env-vars "DATABASE_URL=$DatabaseUrl" "REDIS_URL=$RedisUrl" "AGENT_NAME=$Agent" "AZURE_OPENAI_ENDPOINT=$AiEndpoint" "AZURE_OPENAI_API_KEY=$AiKey" "AZURE_OPENAI_GPT_DEPLOYMENT=$GptDeployment" "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$EmbeddingDeployment"
}

# M7: Async Job Runner
Write-Host ">>> Creating Async Job Runner..." -ForegroundColor Yellow
az containerapp job create `
    --name InvestIQAppNL-mc-job `
    --resource-group $ResourceGroup `
    --environment $EnvName `
    --image "$AcrLoginServer/InvestIQAppNL-api:latest" `
    --registry-server $AcrLoginServer `
    --registry-username $AcrName `
    --registry-password $AcrPassword `
    --trigger-type Manual `
    --replica-timeout 3600 `
    --cpu 2.0 `
    --memory 4.0Gi `
    --env-vars "DATABASE_URL=$DatabaseUrl" "REDIS_URL=$RedisUrl"

# 11. Application Gateway

# Retrieve Container App FQDNs
$ApiFqdn = az containerapp show --name InvestIQAppNL-api --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv
$UiFqdn = az containerapp show --name InvestIQAppNL-ui --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

# API must be externally reachable for AppGW to proxy to it
Write-Host ">>> Switching API ingress to external for Application Gateway..." -ForegroundColor Yellow
az containerapp ingress enable `
    --name InvestIQAppNL-api `
    --resource-group $ResourceGroup `
    --type external `
    --target-port 8000 2>$null

$ApiFqdn = az containerapp show --name InvestIQAppNL-api --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv

Write-Host "    UI  backend: $UiFqdn"
Write-Host "    API backend: $ApiFqdn"

Write-Host ">>> Creating VNet for Application Gateway..." -ForegroundColor Yellow
az network vnet create `
    --resource-group $ResourceGroup `
    --name $AppgwVnet `
    --address-prefix 10.0.0.0/16 `
    --subnet-name $AppgwSubnet `
    --subnet-prefix 10.0.0.0/24 `
    --location $Location

Write-Host ">>> Creating Public IP for Application Gateway..." -ForegroundColor Yellow
az network public-ip create `
    --resource-group $ResourceGroup `
    --name $AppgwPip `
    --sku Standard `
    --allocation-method Static `
    --location $Location

Write-Host ">>> Creating Application Gateway (this may take a few minutes)..." -ForegroundColor Yellow
az network application-gateway create `
    --resource-group $ResourceGroup `
    --name $AppgwName `
    --location $Location `
    --sku Standard_v2 `
    --capacity 1 `
    --vnet-name $AppgwVnet `
    --subnet $AppgwSubnet `
    --public-ip-address $AppgwPip `
    --frontend-port 80 `
    --http-settings-port 443 `
    --http-settings-protocol Https `
    --servers $UiFqdn `
    --priority 100

Write-Host ">>> Configuring backend HTTP settings..." -ForegroundColor Yellow
az network application-gateway http-settings update `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name appGatewayBackendHttpSettings `
    --port 443 `
    --protocol Https `
    --host-name-from-backend-pool true

Write-Host ">>> Creating health probes..." -ForegroundColor Yellow
az network application-gateway probe create `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name ui-probe `
    --protocol Https `
    --host-name-from-http-settings true `
    --path "/" `
    --interval 30 `
    --timeout 30 `
    --threshold 3 2>$null

az network application-gateway http-settings update `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name appGatewayBackendHttpSettings `
    --probe ui-probe

Write-Host ">>> Adding API backend pool..." -ForegroundColor Yellow
az network application-gateway address-pool create `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name api-backend `
    --servers $ApiFqdn 2>$null

az network application-gateway http-settings create `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name api-https-settings `
    --port 443 `
    --protocol Https `
    --host-name-from-backend-pool true 2>$null

az network application-gateway probe create `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name api-probe `
    --protocol Https `
    --host-name-from-http-settings true `
    --path "/docs" `
    --interval 30 `
    --timeout 30 `
    --threshold 3 2>$null

az network application-gateway http-settings update `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name api-https-settings `
    --probe api-probe

Write-Host ">>> Configuring path-based routing..." -ForegroundColor Yellow
az network application-gateway url-path-map create `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name investiqappnl-routing `
    --default-address-pool appGatewayBackendPool `
    --default-http-settings appGatewayBackendHttpSettings `
    --paths "/api/*" `
    --address-pool api-backend `
    --http-settings api-https-settings `
    --rule-name api-path-rule 2>$null

az network application-gateway rule update `
    --resource-group $ResourceGroup `
    --gateway-name $AppgwName `
    --name rule1 `
    --rule-type PathBasedRouting `
    --url-path-map investiqappnl-routing `
    --priority 100

$AppgwPipAddress = az network public-ip show `
    --resource-group $ResourceGroup `
    --name $AppgwPip `
    --query ipAddress -o tsv

Write-Host ">>> Application Gateway deployed." -ForegroundColor Green
Write-Host "    Public IP: $AppgwPipAddress"
Write-Host "    URL:       http://$AppgwPipAddress"

# Summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "DEPLOYMENT COMPLETE" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "UI URL:          https://$UiFqdn"
Write-Host "API:             https://$ApiFqdn"
Write-Host "App Gateway:     http://$AppgwPipAddress"
Write-Host "PostgreSQL:      $PostgresFqdn"
Write-Host "Redis:           $RedisHost"
Write-Host "Storage:         $StorageAccount"
Write-Host "Key Vault:       $KeyVaultName"
Write-Host "AI Foundry Hub:  $AiHubName"
Write-Host "AI Project:      $AiProjectName"
Write-Host "AI Endpoint:     $AiEndpoint"
Write-Host "GPT Deployment:  $GptDeployment"
Write-Host "Embed Deployment:$EmbeddingDeployment"
Write-Host ""
Write-Host "IMPORTANT - Store these credentials:" -ForegroundColor Red
Write-Host "  Postgres Password: $PostgresPassword"
Write-Host "  Database URL:      $DatabaseUrl"
Write-Host "  AI Key Loaded:     $(-not [string]::IsNullOrEmpty($AiKey))"
Write-Host "============================================" -ForegroundColor Green
