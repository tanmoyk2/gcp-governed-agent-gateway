#!/bin/bash

export CLOUDSDK_CORE_DISABLE_PROMPTS=1

echo "CLEANUP-SCRIPT START"

export PROJECT_ID=$(gcloud config get-value project)
export PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format 'value(projectNumber)')
export REGION=${REGION:-$(gcloud compute project-info describe --format="value[](commonInstanceMetadata.items.google-compute-default-region)" 2>/dev/null)}
export REGION=${REGION:-us-central1}

echo "Target Project: ${PROJECT_ID}"
echo "Target Region:  ${REGION}"
echo "--------------------------------------------------"

# 1. Delete Reasoning Engine (Agent Runtime instance)
echo "[1/3] Deleting Agent Runtime reasoning engine(s)..."
RESPONSE="$(
  curl -s \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" || true
)"

ENGINES="$(
  echo "$RESPONSE" |
  jq -r '.reasoningEngines[]?.name // empty'
)"

if [[ -n "$ENGINES" ]]; then
  while IFS= read -r re; do
    [[ -z "$re" ]] && continue
    echo "  -> Deleting Reasoning Engine: $(basename "${re}")"
    curl -sf -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      "https://${REGION}-aiplatform.googleapis.com/v1/${re}?force=true" >/dev/null || true
  done <<< "$ENGINES"
else
  echo "  -> No Reasoning Engines found."
fi


# 2. Delete Authz Policies targeting the gateway (Required Blocker)
echo "[2/3] Deleting Authz Policies attached to the gateway..."
for policy in $(gcloud network-security authz-policies list --project="${PROJECT_ID}" --location="${REGION}" --format="value(name)" 2>/dev/null); do
  echo "  -> Deleting Authz Policy: $(basename "${policy}")"
  gcloud network-security authz-policies delete "$(basename "${policy}")" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --quiet
done

# 3. Delete all Agent Gateways in the region
echo "[3/3] Deleting Agent Gateways in region ${REGION}..."
for gw in $(gcloud network-services agent-gateways list --project="${PROJECT_ID}" --location="${REGION}" --format="value(name)" 2>/dev/null); do
  gw_name=$(basename "${gw}")
  echo "  -> Deleting Agent Gateway: ${gw_name}"
  gcloud network-services agent-gateways delete "${gw_name}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --quiet
done

echo "--------------------------------------------------"
echo "Agent Gateways successfully cleared."

echo "CLEANUP-SCRIPT END"
