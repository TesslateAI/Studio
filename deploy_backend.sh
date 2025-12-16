#!/bin/bash
set -e

ECR_REPO="<ECR_REGISTRY>"

echo "Logging into ECR..."
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_REPO

echo "Tagging image..."
docker tag tesslate-backend:latest $ECR_REPO/tesslate-backend:latest

echo "Pushing to ECR..."
docker push $ECR_REPO/tesslate-backend:latest

echo "Restarting deployment..."
kubectl rollout restart deployment/tesslate-backend -n tesslate

echo "Waiting for rollout..."
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s

echo "Done!"
