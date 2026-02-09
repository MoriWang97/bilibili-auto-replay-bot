# Bilibili Bot - Azure Container Apps 部署脚本
# 使用前请确保已登录 Azure CLI: az login

# ── 配置变量 ────────────────────────────────────────────────
$RESOURCE_GROUP = "bilibili-bot-rg"
$LOCATION = "eastasia"
$CONTAINER_APP_ENV = "bilibili-bot-env"
$CONTAINER_APP_NAME = "bilibili-bot"
$ACR_NAME = "bilibotacr"  # 必须全局唯一，只能小写字母和数字
$KEYVAULT_NAME = "aetherkeyvault"

# Azure OpenAI 配置
$AZURE_OPENAI_ENDPOINT = "https://ai-wsen19976766ai022928044101.cognitiveservices.azure.com/"
$AZURE_OPENAI_DEPLOYMENT = "gpt-5.2"

# ── 1. 创建资源组 ───────────────────────────────────────────
Write-Host "📦 创建资源组..." -ForegroundColor Cyan
az group create --name $RESOURCE_GROUP --location $LOCATION --output none

# ── 2. 创建 Azure Container Registry ───────────────────────
Write-Host "🐳 创建容器注册表..." -ForegroundColor Cyan
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true --output none
az acr login --name $ACR_NAME

# ── 3. 构建并推送 Docker 镜像 ───────────────────────────────
Write-Host "🔨 构建并推送 Docker 镜像..." -ForegroundColor Cyan
$IMAGE_NAME = "$ACR_NAME.azurecr.io/bilibili-bot:latest"
az acr build --registry $ACR_NAME --image bilibili-bot:latest .

# ── 4. 创建 Container Apps 环境 ────────────────────────────
Write-Host "🌐 创建 Container Apps 环境..." -ForegroundColor Cyan
az containerapp env create `
    --name $CONTAINER_APP_ENV `
    --resource-group $RESOURCE_GROUP `
    --location $LOCATION `
    --output none

# ── 5. 获取 ACR 凭据 ────────────────────────────────────────
Write-Host "🔐 获取 ACR 凭据..." -ForegroundColor Cyan
$ACR_PASSWORD = (az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv)

# ── 6. 创建 Container App（带托管身份） ─────────────────────
Write-Host "🚀 创建 Container App..." -ForegroundColor Cyan
az containerapp create `
    --name $CONTAINER_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --environment $CONTAINER_APP_ENV `
    --image $IMAGE_NAME `
    --registry-server "$ACR_NAME.azurecr.io" `
    --registry-username $ACR_NAME `
    --registry-password $ACR_PASSWORD `
    --cpu 0.25 `
    --memory 0.5Gi `
    --min-replicas 1 `
    --max-replicas 1 `
    --env-vars `
        "AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT" `
        "AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT" `
        "KEYVAULT_URL=https://$KEYVAULT_NAME.vault.azure.net/" `
        "BOT_POLL_INTERVAL=60" `
        "LOG_LEVEL=INFO" `
    --system-assigned `
    --output none

# ── 7. 获取托管身份并授权 Key Vault ─────────────────────────
Write-Host "🔑 配置 Key Vault 访问权限..." -ForegroundColor Cyan
$PRINCIPAL_ID = (az containerapp show `
    --name $CONTAINER_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --query "identity.principalId" -o tsv)

# 获取 Key Vault 资源 ID（Key Vault 可能在其他资源组）
$KV_ID = (az keyvault show --name $KEYVAULT_NAME --query "id" -o tsv)

# 使用 RBAC 授权（Key Vault 启用了 RBAC 模式）
az role assignment create `
    --role "Key Vault Secrets User" `
    --assignee-object-id $PRINCIPAL_ID `
    --assignee-principal-type ServicePrincipal `
    --scope $KV_ID `
    --output none 2>$null

Write-Host "  Principal ID: $PRINCIPAL_ID"
Write-Host "  Key Vault: $KEYVAULT_NAME"

# ── 8. 完成 ─────────────────────────────────────────────────
Write-Host ""
Write-Host "✅ 部署完成！" -ForegroundColor Green
Write-Host ""
Write-Host "查看日志:" -ForegroundColor Yellow
Write-Host "  az containerapp logs show -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP --follow"
Write-Host ""
Write-Host "重启应用:" -ForegroundColor Yellow
Write-Host "  az containerapp revision restart -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP"
Write-Host ""
Write-Host "更新镜像:" -ForegroundColor Yellow
Write-Host "  az acr build --registry $ACR_NAME --image bilibili-bot:latest ."
Write-Host "  az containerapp update -n $CONTAINER_APP_NAME -g $RESOURCE_GROUP --image $IMAGE_NAME"
