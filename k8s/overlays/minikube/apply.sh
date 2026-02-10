#!/bin/bash
kubectl apply -k k8s/overlays/minikube
kubectl patch ingress tesslate-ingress -n tesslate --type='json' -p='[{"op":"remove","path":"/spec/rules/0/host"}]'
