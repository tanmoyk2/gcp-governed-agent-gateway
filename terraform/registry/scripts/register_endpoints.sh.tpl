#!/bin/bash

# Validation
if [ -z "$PROJECT_ID" ] || [ -z "$LOCATION" ]; then
  echo "Error: PROJECT_ID and LOCATION environment variables must be set."
  exit 1
fi

echo "Deploying Agent Registry Services for: $PROJECT_ID in $LOCATION"

# Helper function for no-spec registration
reg_svc() {
  local svc_id=$1
  local display_name=$2
  local url=$3
  local desc=$4

  # Check if service already exists
  if gcloud alpha agent-registry services describe "$svc_id" --project="$PROJECT_ID" --location="$LOCATION" >/dev/null 2>&1; then
    echo "Service $svc_id already exists, skipping creation."
    return 0
  fi

  echo "Registering: $svc_id ($display_name) at $url"

  gcloud alpha agent-registry services create "$svc_id" \
    --project="$PROJECT_ID" \
    --location="$LOCATION" \
    --display-name="$display_name" \
    --endpoint-spec-type=no-spec \
    $${desc:+--description="$desc"} \
    --interfaces="url=$url,protocolBinding=JSONRPC"
}

### 1. Google APIs with multiple variants
%{ for id, name in google_apis ~}
# Variants for ${name} (${id})
reg_svc "${id}" "${name}" "https://${id}.googleapis.com"
reg_svc "${id}-mtls" "${name} mTLS" "https://${id}.mtls.googleapis.com"
reg_svc "$${LOCATION}-${id}" "${name} Locational" "https://$${LOCATION}-${id}.googleapis.com"
reg_svc "$${LOCATION}-${id}-mtls" "${name} Locational mTLS" "https://$${LOCATION}-${id}.mtls.googleapis.com"
reg_svc "${id}-$${LOCATION}-rep" "${name} Regional (REP)" "https://${id}.$${LOCATION}.rep.googleapis.com"
%{ endfor ~}

echo "Full deployment for region $LOCATION complete."
