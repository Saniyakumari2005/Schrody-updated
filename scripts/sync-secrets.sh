#!/usr/bin/env bash
# Pulls the bot's secrets out of GCP Secret Manager (the single source of truth)
# and creates/updates the schrody-bot-secrets Kubernetes Secret from them.
# Run this locally after `gcloud auth login` + `gcloud container clusters
# get-credentials`, or let CI run it (it uses the same gcloud/kubectl auth
# already configured in the workflow).
set -euo pipefail

NAMESPACE="schrody-bot"
SECRET_NAME="schrody-bot-secrets"

# Secret Manager secret names -> env var names the bot expects
declare -A SECRETS=(
  [discord-token]=DISCORD_TOKEN
  [mongo-url]=MONGO_URL
  [mongo-db]=MONGO_DB
  [mongo-identity-db]=MONGO_IDENTITY_DB
  [gemini-api-key]=GEMINI_API_KEY
  [gemini-model]=GEMINI_MODEL
  [privacy-salt]=PRIVACY_SALT
  [google-token]=GOOGLE_TOKEN
)

ARGS=()
for secret_id in "${!SECRETS[@]}"; do
  env_name="${SECRETS[$secret_id]}"
  if value="$(gcloud secrets versions access latest --secret="${secret_id}" 2>/dev/null)"; then
    ARGS+=("--from-literal=${env_name}=${value}")
    echo "  Synced secret: ${secret_id} -> ${env_name}"
  else
    echo "  ⚠️ Warning: Secret '${secret_id}' not found in Secret Manager, skipping."
  fi
done

kubectl create secret generic "${SECRET_NAME}" \
  --namespace="${NAMESPACE}" \
  "${ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ ${SECRET_NAME} synced from Secret Manager into namespace ${NAMESPACE}"
