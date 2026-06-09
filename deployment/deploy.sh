#!/bin/bash
set -e

# Default values
NAMESPACE="default"
SECRET_VALUE=""
RELEASE_NAME="dokops"
CHART_PATH="./helm/dokops-aio"

# Function to print usage
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -s, --secret <value>    Auth Secret Key (Required)"
    echo "  -n, --namespace <name>  Kubernetes Namespace (Default: default)"
    echo "  -h, --help              Show this help message"
    exit 1
}

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -s|--secret) SECRET_VALUE="$2"; shift ;;
        -n|--namespace) NAMESPACE="$2"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown parameter passed: $1"; usage ;;
    esac
    shift
done

echo "🚀 Starting DokOps-AIO Deployment..."

# Interactive Prompts if arguments missing
if [ -z "$NAMESPACE" ]; then
    read -p "Enter Namespace [default]: " INPUT_NS
    NAMESPACE=${INPUT_NS:-default}
fi

if [ -z "$SECRET_VALUE" ]; then
    echo -n "Enter Auth Secret Key: "
    read -s SECRET_VALUE
    echo "" # Newline after silent input
fi

if [ -z "$SECRET_VALUE" ]; then
    echo "❌ Error: Secret key is required!"
    exit 1
fi

echo "----------------------------------------"
echo "Target Namespace: $NAMESPACE"
echo "Release Name:     $RELEASE_NAME"
echo "----------------------------------------"

# 1. Create Secret
echo "🔐 Managing Secrets..."
# Check if secret exists
if kubectl get secret dokops-aio-secrets -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "ℹ️  Secret 'dokops-aio-secrets' already exists. Skipping creation."
    echo "⚠️  (If you need to update it, delete it first: kubectl delete secret dokops-aio-secrets -n $NAMESPACE)"
else
    kubectl create secret generic dokops-aio-secrets \
        --from-literal=auth-secret="$SECRET_VALUE" \
        -n "$NAMESPACE"
    echo "✅ Secret 'dokops-aio-secrets' created."
fi

# 2. Deploy Helm Chart
echo "☸️  Deploying Helm Chart..."
helm upgrade --install "$RELEASE_NAME" "$CHART_PATH" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    --set ingress.enabled=true \
    --set ingress.hosts[0].host="dokops.local"

echo "----------------------------------------"
echo "✅ Deployment Complete!"
echo "----------------------------------------"
echo "Verify with:"
echo "  kubectl get pods -n $NAMESPACE"
echo "  kubectl get secret dokops-aio-secrets -n $NAMESPACE"
