# Microservices Project Setup Guide

## Prerequisites
- AWS CLI configured with appropriate permissions
- kubectl installed
- Helm 3 installed
- Access to AWS EKS (Elastic Kubernetes Service)

## Step 1: Cluster Setup

### 1.1 Create EKS Cluster
```bash
eksctl create cluster \
    --name microservices-cluster \
    --region us-east-1 \
    --nodegroup-name standard-workers \
    --node-type t3.large \
    --nodes 3 \
    --nodes-min 1 \
    --nodes-max 4 \
    --managed
1.2 Configure kubectl
bashCopyaws eks update-kubeconfig --name microservices-cluster --region us-east-1
1.3 Create Namespace
bashCopykubectl create namespace microservices
Step 2: Database Setup (YugabyteDB)
2.1 Add YugabyteDB Helm Repository
bashCopyhelm repo add yugabytedb https://charts.yugabyte.com
helm repo update
2.2 Create Storage Class
bashCopykubectl apply -f kubernetes/storage/storage-class.yaml
2.3 Install YugabyteDB
bashCopyhelm install yugabyte-db yugabytedb/yugabyte \
    --namespace microservices \
    --set storage.master.storageClass=gp2-yugabyte \
    --set storage.tserver.storageClass=gp2-yugabyte \
    --set resource.master.requests.cpu=1 \
    --set resource.master.requests.memory=1Gi \
    --set resource.tserver.requests.cpu=1 \
    --set resource.tserver.requests.memory=1Gi
Step 3: API Gateway Setup (APISIX)
3.1 Add APISIX Helm Repository
bashCopyhelm repo add apisix https://charts.apiseven.com
helm repo update
3.2 Install APISIX
bashCopyhelm install apisix apisix/apisix \
    --namespace microservices \
    --set gateway.type=LoadBalancer \
    --set ingress-controller.enabled=true \
    --set admin.allow.ipList="{0.0.0.0/0}"
3.3 Configure Routes
bashCopykubectl apply -f kubernetes/apisix/routes.yaml
Step 4: Open Policy Agent (OPA) Setup
4.1 Create OPA ConfigMap
bashCopykubectl apply -f kubernetes/opa/configmap.yaml
4.2 Deploy OPA
bashCopykubectl apply -f kubernetes/opa/deployment.yaml
kubectl apply -f kubernetes/opa/service.yaml
4.3 Apply Policies
bashCopykubectl apply -f kubernetes/opa/policies/
Step 5: KEDA Setup
5.1 Install KEDA
bashCopyhelm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace
5.2 Configure Scalers
bashCopykubectl apply -f kubernetes/keda/product-scaler.yaml
kubectl apply -f kubernetes/keda/order-scaler.yaml
Step 6: Microservices Deployment
6.1 Deploy Product Service
bashCopykubectl apply -f kubernetes/microservices/product-service/deployment.yaml
kubectl apply -f kubernetes/microservices/product-service/service.yaml
6.2 Deploy Order Service
bashCopykubectl apply -f kubernetes/microservices/order-service/deployment.yaml
kubectl apply -f kubernetes/microservices/order-service/service.yaml
Step 7: Monitoring Setup
7.1 Install Prometheus & Grafana
bashCopyhelm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring \
    --create-namespace
7.2 Configure Service Monitors
bashCopykubectl apply -f kubernetes/monitoring/service-monitors.yaml
Step 8: Verification
8.1 Check All Components
bashCopy# Check all pods
kubectl get pods -n microservices

# Check services
kubectl get svc -n microservices

# Check APISIX routes
kubectl get apisixroute -n microservices

# Check KEDA scalers
kubectl get scaledobject -n microservices
8.2 Test API Endpoints
bashCopy# Get APISIX Gateway URL
export GATEWAY_IP=$(kubectl get svc apisix-gateway -n microservices -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Test endpoints
curl -H "Host: api.microservices.local" http://$GATEWAY_IP/products/
curl -H "Host: api.microservices.local" http://$GATEWAY_IP/orders/
Troubleshooting
Common Issues

YugabyteDB not starting
bashCopykubectl describe pod -n microservices -l app=yb-master

APISIX routes not working
bashCopykubectl logs -n microservices -l app.kubernetes.io/name=apisix

KEDA scaling issues
bashCopykubectl describe scaledobject -n microservices


Resource Cleanup
Clean up resources when done
bashCopy# Delete all resources in microservices namespace
kubectl delete namespace microservices

# Delete EKS cluster
eksctl delete cluster --name microservices-cluster --region us-east-1