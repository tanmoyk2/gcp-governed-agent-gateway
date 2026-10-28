#!/bin/bash
# End-to-End Automated Deployment Script for Governed Agent Egress
# Reconstructed from session history: Terraform + Cloud Run MCP + Vertex AI ADK Agent + Agent Registry + IAP + Model Armor

set -euo pipefail

export PROJECT_ID=$(gcloud config get-value project)
export REGION=${REGION:-us-central1}
export AGENT_NAME="hello-world-agent"
export PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
export ORGANIZATION_ID=$(gcloud projects get-ancestors "${PROJECT_ID}" --format=json 2>/dev/null | jq -r '.[] | select(.type=="organization") | .id')
export USER_PROJECT_OVERRIDE=true
export GOOGLE_BILLING_PROJECT="${PROJECT_ID}"
export PATH="$HOME/.local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=================================================="
echo "Project ID:      ${PROJECT_ID}"
echo "Project Number:  ${PROJECT_NUMBER}"
echo "Organization ID: ${ORGANIZATION_ID}"
echo "Region:          ${REGION}"
echo "=================================================="

# 1. Create Vertex AI Service Identity
gcloud beta services identity create --service=aiplatform.googleapis.com --project="${PROJECT_ID}" --quiet

# 2. Provision Base Infrastructure & Agent Gateway (Dry-Run Mode)
cd "${REPO_ROOT}/terraform"
terraform init
terraform apply -auto-approve -lock-timeout=600s \
  -var=project_id="${PROJECT_ID}" \
  -var=project_number="${PROJECT_NUMBER}" \
  -var=region="${REGION}" \
  -var=organization_id="${ORGANIZATION_ID}" \
  -var=enable_iap_enforcement=false \
  -var=agent_gateway_name=gateway-egress \
  -var=artifact_registry_repo=agent-repo \
  -var=vpc_network_name=governed-agent-vpc \
  -var=subnet_name=agent-private-subnet \
  -var=network_attachment_name=gateway-egress-na \
  -var=enable_model_armor=false \
  -var=model_armor_request_template_id=agw-request-template \
  -var=model_armor_response_template_id=agw-response-template \
  -var=model_armor_inspect_template_id=agw-ssn-inspect-template \
  -var=model_armor_deidentify_template_id=agw-ssn-redaction-template \
  -var=enable_vertex_ai_integration=true \
  -var=vertex_ai_inspect_only=false

# 3. Deploy Cloud Run Sample MCP Tool Server
cd "${REPO_ROOT}/mcp-servers/sample-tool"
gcloud run deploy agents-everywhere-sample-tool \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --source=. \
  --memory=4Gi \
  --cpu=1 \
  --min-instances=1 \
  --max-instances=10 \
  --concurrency=8 \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --port=8080 \
  --service-account="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --update-env-vars=AGENT_VERSION=0.1.0

# 4. Register MCP Tool Server in Agent Registry
export TOOL_SERVICE_URL=$(gcloud run services describe agents-everywhere-sample-tool \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://agentregistry.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/${REGION}/services?serviceId=agents-everywhere-sample-tool" \
  -d "{
    \"displayName\": \"agents-everywhere-sample-tool\",
    \"description\": \"Sample MCP Tool Service managed by REST framework.\",
    \"interfaces\": [
      {
        \"url\": \"${TOOL_SERVICE_URL}\",
        \"protocolBinding\": \"JSONRPC\"
      }
    ],
    \"mcpServerSpec\": {
      \"type\": \"TOOL_SPEC\",
      \"content\": {
        \"tools\": [
          {
            \"name\": \"get_capital\",
            \"description\": \"Retrieves the capital city of a specified country.\",
            \"inputSchema\": {
              \"type\": \"object\",
              \"properties\": {
                \"location\": {\"title\": \"Location\", \"type\": \"string\"}
              },
              \"required\": [\"location\"]
            }
          },
          {
            \"name\": \"get_hostname\",
            \"description\": \"Retrieves the hostname of the server running the tool.\",
            \"inputSchema\": {
              \"type\": \"object\",
              \"properties\": {},
              \"required\": []
            }
          },
          {
            \"name\": \"get_sanitized_record\",
            \"description\": \"Returns the sanitized message received from the user after Model Armor applies the Sensitive Data Protection template.\",
            \"inputSchema\": {
              \"type\": \"object\",
              \"properties\": {
                \"record\": {\"title\": \"Record\", \"type\": \"string\"}
              },
              \"required\": [\"record\"]
            }
          }
        ]
      }
    }
  }"

# 5. Deploy ADK Hello World Agent with Agent Identity & Patch Egress Gateway
cd "${REPO_ROOT}/agents/hello_agent"
agents-cli deploy \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --agent-identity \
  --no-confirm-project

export INSTANCE_ID=$(curl -s -X GET "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" | jq -r '.reasoningEngines[]? | select(.displayName == "'"${AGENT_NAME}"'" or .displayName == "'"${AGENT_NAME//-/_}"'") | .name' | awk -F'/' '{print $NF}' | head -n 1)
echo "Deployed Agent Runtime Instance ID: ${INSTANCE_ID}"

export ENV_CONFIG='[{"name":"GOOGLE_API_ENABLE_RUNTIME_BOUND_TOKEN","value":"false"},{"name":"GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES","value":"false"}]'
export PACKAGE_SPEC=$(curl -s -X GET "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" | jq -c '.spec.packageSpec // empty')

if [ -n "$PACKAGE_SPEC" ] && [ "$PACKAGE_SPEC" != "null" ]; then
  export UPDATE_MASK="spec.deploymentSpec.agentGatewayConfig,spec.deploymentSpec.env,spec.packageSpec"
  export PATCH_PAYLOAD="{\"spec\": {\"packageSpec\": ${PACKAGE_SPEC}, \"deploymentSpec\": {\"agentGatewayConfig\": {\"agentToAnywhereConfig\": {\"agentGateway\": \"projects/${PROJECT_ID}/locations/${REGION}/agentGateways/gateway-egress\"}}, \"env\": ${ENV_CONFIG}}}}"
else
  export UPDATE_MASK="spec.deploymentSpec.agentGatewayConfig,spec.deploymentSpec.env"
  export PATCH_PAYLOAD="{\"spec\": {\"deploymentSpec\": {\"agentGatewayConfig\": {\"agentToAnywhereConfig\": {\"agentGateway\": \"projects/${PROJECT_ID}/locations/${REGION}/agentGateways/gateway-egress\"}}, \"env\": ${ENV_CONFIG}}}}"
fi

curl -i -X PATCH "https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}?updateMask=${UPDATE_MASK}" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -d "${PATCH_PAYLOAD}"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="principalSet://agents.global.org-${ORGANIZATION_ID}.system.id.goog/attribute.platformContainer/aiplatform/projects/${PROJECT_NUMBER}" \
  --role="roles/browser" --quiet

# 6. Register hello-world-agent in Agent Registry
export HELLO_WORLD_AGENT_URL="https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}/api"
gcloud alpha agent-registry services create hello-world-agent \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --display-name="hello-world-agent" \
  --description="hello-world-agent ADK Agent managed by REST framework." \
  --interfaces="url=${HELLO_WORLD_AGENT_URL},protocolBinding=HTTP_JSON" \
  --agent-spec-type="NO_SPEC" || true

# 7. Bind Cloud Run & IAP Egressor IAM Policies and Enforce IAP
gcloud run services add-iam-policy-binding agents-everywhere-sample-tool \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet

gcloud run services add-iam-policy-binding agents-everywhere-sample-tool \
  --member="principal://agents.global.org-${ORGANIZATION_ID}.system.id.goog/resources/aiplatform/projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}" \
  --role="roles/run.invoker" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" --quiet

gcloud iam service-accounts add-iam-policy-binding "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --member="principal://agents.global.org-${ORGANIZATION_ID}.system.id.goog/resources/aiplatform/projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT_ID}" --quiet

export MCP_SERVER_UUID=$(curl -s "https://agentregistry.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/${REGION}/services/agents-everywhere-sample-tool" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" | grep -o '"registryResource": "[^"]*' | cut -d'/' -f6)

curl -s -X POST "https://iap.googleapis.com/v1/projects/${PROJECT_NUMBER}/locations/${REGION}/iap_web/agentRegistry/mcpServers/${MCP_SERVER_UUID}:setIamPolicy" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "Content-Type: application/json" \
  -d "{
    \"policy\": {
      \"bindings\": [
        {
          \"role\": \"roles/iap.egressor\",
          \"members\": [
            \"principal://agents.global.org-${ORGANIZATION_ID}.system.id.goog/resources/aiplatform/projects/${PROJECT_NUMBER}/locations/${REGION}/reasoningEngines/${INSTANCE_ID}\"
          ]
        }
      ]
    }
  }"

# 8. Enable Active IAP Enforcement & Model Armor + Cloud DLP Governance
cd "${REPO_ROOT}/terraform"
terraform apply -auto-approve -lock-timeout=600s \
  -var=project_id="${PROJECT_ID}" \
  -var=project_number="${PROJECT_NUMBER}" \
  -var=region="${REGION}" \
  -var=organization_id="${ORGANIZATION_ID}" \
  -var=enable_iap_enforcement=true \
  -var=agent_gateway_name=gateway-egress \
  -var=artifact_registry_repo=agent-repo \
  -var=vpc_network_name=governed-agent-vpc \
  -var=subnet_name=agent-private-subnet \
  -var=network_attachment_name=gateway-egress-na \
  -var=enable_model_armor=true \
  -var=enable_vertex_ai_integration=true \
  -var=vertex_ai_inspect_only=false \
  -var=model_armor_request_template_id=agw-request-template \
  -var=model_armor_response_template_id=agw-response-template \
  -var=model_armor_inspect_template_id=agw-ssn-inspect-template \
  -var=model_armor_deidentify_template_id=agw-ssn-redaction-template

echo "Deployment complete!"
