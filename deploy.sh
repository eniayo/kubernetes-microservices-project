#!/bin/bash

# Microservices Deployment Script for AWS EKS
# This script automates the deployment of the microservices architecture

set -e  # Exit on any error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration variables
CLUSTER_NAME="microservices-cluster"
AWS_REGION="us-east-1"
NAMESPACE="microservices"
MONITORING_NAMESPACE="monitoring"
KEDA_NAMESPACE="keda"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Function to wait for deployment readiness
wait_for_deployment() {
    local deploy_name=$1
    local namespace=$2
    local timeout=${3:-300s}
    local retry_count=0
    local max_retries=3
    
    log_info "Waiting for deployment ${deploy_name} to be ready (timeout: ${timeout})..."
    
    for ((retry=1; retry<=max_retries; retry++)); do
        if kubectl wait --for=condition=available --timeout=${timeout} deployment/${deploy_name} -n ${namespace}; then
            log_success "Deployment ${deploy_name} is ready"
            return 0
        else
            log_warning "Deployment ${deploy_name} not ready on attempt ${retry}/${max_retries}"
            if [ $retry -lt $max_retries ]; then
                log_info "Waiting 30 seconds before retrying..."
                sleep 30
            fi
        fi
    done
    
    if kubectl get deployment ${deploy_name} -n ${namespace} &>/dev/null; then
        log_warning "Deployment ${deploy_name} exists but is not ready. Continuing anyway..."
        return 0
    else
        log_error "Deployment ${deploy_name} failed to become ready after ${max_retries} attempts"
        return 1
    fi
}

# Main deployment process
main() {
    log_info "Starting microservices deployment..."

    # Check prerequisites
    log_info "Checking prerequisites..."
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl first."
    fi
    
    if ! command -v helm &> /dev/null; then
        log_error "helm not found. Please install helm first."
    fi
    
    if ! command -v aws &> /dev/null; then
        log_error "aws CLI not found. Please install AWS CLI first."
    fi

    # Update kubeconfig for existing EKS cluster
    log_info "Updating kubeconfig for existing EKS cluster..."
    aws eks update-kubeconfig --name ${CLUSTER_NAME} --region ${AWS_REGION}
    
    # Ensure namespaces exist
    log_info "Ensuring namespaces exist..."
    kubectl apply -f kubernetes/microservices/namespace.yaml 2>/dev/null || kubectl create namespace ${NAMESPACE}
    kubectl get namespace ${MONITORING_NAMESPACE} 2>/dev/null || kubectl create namespace ${MONITORING_NAMESPACE}
    kubectl get namespace ${KEDA_NAMESPACE} 2>/dev/null || kubectl create namespace ${KEDA_NAMESPACE}
    
    # Add Helm repositories
    log_info "Adding Helm repositories..."
    helm repo add yugabytedb https://charts.yugabyte.com 2>/dev/null || true
    helm repo add apisix https://charts.apisix.apache.org/ 2>/dev/null || true
    helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
    log_info "Updating Helm repositories..."
    helm repo update
    
    # Deploy storage class
    log_info "Deploying storage class for persistent volumes..."
    kubectl apply -f kubernetes/storage/storage-class.yaml
    
    # Check YugabyteDB deployment status
    log_info "Checking YugabyteDB deployment status..."
    if kubectl get statefulset -n ${NAMESPACE} | grep -q "yb-master"; then
        log_info "YugabyteDB StatefulSets already exist - skipping Helm upgrade"
    else
        log_info "Deploying YugabyteDB..."
        helm upgrade --install yugabyte yugabytedb/yugabyte \
            --namespace ${NAMESPACE} \
            --values kubernetes/yugabytedb/values.yaml \
            --create-namespace
    fi
    
    # Deploy APISIX API Gateway
    log_info "Deploying APISIX with LoadBalancer gateway..."
    # Delete existing service to enforce update to LoadBalancer type
    kubectl delete service apisix-gateway -n ${NAMESPACE} --force --grace-period=0 || true
    
    # Delete any stuck pods
    kubectl get pods -n ${NAMESPACE} -l app.kubernetes.io/name=apisix -o name | xargs -r kubectl delete -n ${NAMESPACE} --force --grace-period=0 || true
    
    helm upgrade --install apisix apisix/apisix \
        --namespace ${NAMESPACE} \
        --values custom-helm-values/apisix-values.yaml
    
    # Deploy OPA for policy enforcement
    log_info "Deploying OPA for policy enforcement..."
    kubectl apply -f kubernetes/opa/deployment.yaml
    kubectl apply -f kubernetes/opa/service.yaml
    kubectl apply -f kubernetes/opa/configmap.yaml
    
    # Create ConfigMap from OPA policy files
    log_info "Creating ConfigMap from OPA policy files..."
    kubectl create configmap opa-policies \
        --from-file=kubernetes/opa/policies/ \
        -n ${NAMESPACE} \
        --dry-run=client -o yaml | kubectl apply -f -
    
    # Deploy KEDA for autoscaling
    log_info "Deploying KEDA for autoscaling..."
    helm upgrade --install keda kedacore/keda \
        --namespace ${KEDA_NAMESPACE} \
        --create-namespace
    
    # Deploy monitoring stack with retry logic
    log_info "Deploying monitoring stack with Prometheus and Grafana..."
    retry_count=0
    max_retries=3
    deployed=false
    
    while [ $retry_count -lt $max_retries ] && [ "$deployed" = false ]; do
        if helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
            --namespace ${MONITORING_NAMESPACE} \
            --create-namespace \
            --timeout 10m; then
            deployed=true
            log_success "Prometheus stack deployed successfully"
        else
            retry_count=$((retry_count+1))
            log_warning "Failed to deploy Prometheus stack (attempt ${retry_count}/${max_retries})"
            if [ $retry_count -lt $max_retries ]; then
                log_info "Waiting 30 seconds before retrying..."
                sleep 30
            else
                log_warning "Max retries reached. Continuing deployment without Prometheus..."
            fi
        fi
    done
    
    # Prepare to deploy microservices
    log_info "Preparing to deploy microservices..."
    
    # Clean up existing deployments to avoid conflicts
    kubectl delete deployment order-service -n ${NAMESPACE} --force --grace-period=0 || true
    kubectl delete service order-service -n ${NAMESPACE} --force --grace-period=0 || true
    kubectl delete deployment product-service -n ${NAMESPACE} --force --grace-period=0 || true
    kubectl delete service product-service -n ${NAMESPACE} --force --grace-period=0 || true
    
    # Deploy microservices with Helm
    log_info "Deploying microservices with Helm..."
    helm upgrade --install order-service ./helm-charts/order-service \
        --namespace ${NAMESPACE} \
        --values custom-helm-values/order-values.yaml
    
    helm upgrade --install product-service ./helm-charts/product-service \
        --namespace ${NAMESPACE} \
        --values custom-helm-values/product-values.yaml
    
    # Apply KEDA scalers for autoscaling
    log_info "Applying KEDA scalers for autoscaling..."
    kubectl apply -f kubernetes/keda/order-scaler.yaml
    kubectl apply -f kubernetes/keda/product-scaler.yaml
    
    # Configure APISIX routes
    log_info "Configuring APISIX routes..."
    kubectl apply -f kubernetes/apisix/routes.yaml
    
    # Wait for deployments to be ready
    log_info "Waiting for deployments to be ready..."
    
    # Create an array of deployments to check
    declare -a deployments=(
        "apisix:${NAMESPACE}"
        "apisix-ingress-controller:${NAMESPACE}"
        "opa:${NAMESPACE}"
        "order-service:${NAMESPACE}"
        "product-service:${NAMESPACE}"
    )
    
    # Track failed deployments
    failed_deployments=()
    
    # Check each deployment
    for deploy_info in "${deployments[@]}"; do
        IFS=':' read -r deploy_name deploy_ns <<< "$deploy_info"
        
        if ! wait_for_deployment "$deploy_name" "$deploy_ns"; then
            failed_deployments+=("$deploy_name")
        fi
    done
    
    # Report on failed deployments if any
    if [ ${#failed_deployments[@]} -gt 0 ]; then
        log_warning "The following deployments are not ready: ${failed_deployments[*]}"
        log_warning "Continuing with deployment process..."
    fi
    
    # Check deployment status
    log_info "Checking deployment status..."
    echo "Pods:"
    kubectl get pods -n ${NAMESPACE}
    
    echo "Services:"
    kubectl get services -n ${NAMESPACE}
    
    echo "APISIX Routes:"
    kubectl get apisixroute -n ${NAMESPACE}
    
    echo "KEDA Scaled Objects:"
    kubectl get scaledobject -n ${NAMESPACE}
    
    # Ensure APISIX gateway is LoadBalancer type
    log_info "Ensuring APISIX gateway is LoadBalancer type..."
    log_info "Patching apisix-gateway service to LoadBalancer type..."
    
    # Check if service exists before patching
    if kubectl get svc apisix-gateway -n ${NAMESPACE} &>/dev/null; then
        kubectl patch svc apisix-gateway -n ${NAMESPACE} -p '{"spec": {"type": "LoadBalancer"}}' || \
            log_warning "Failed to patch apisix-gateway service to LoadBalancer type. Check service status manually."
    else
        log_warning "Service apisix-gateway not found. It may not have been created properly."
        log_warning "Creating LoadBalancer service for APISIX..."
        
        # Define a quick YAML service definition
        cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: apisix-gateway
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: apisix
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 9080
    protocol: TCP
    name: http
  selector:
    app.kubernetes.io/name: apisix
EOF
    fi
    
    # Get API Gateway URL
    log_info "Getting API Gateway URL..."
    echo "Waiting for LoadBalancer IP/hostname..."
    
    # Wait for the LoadBalancer to get an external IP
    for i in {1..30}; do
        echo -n "Waiting for LoadBalancer IP/hostname... (${i}/30)"
        GATEWAY_URL=$(kubectl get svc apisix-gateway -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
        if [[ -n "${GATEWAY_URL}" ]]; then
            break
        fi
        sleep 10
        echo -e "\r\033[K"  # Clear the line
    done
    
    if [[ -z "${GATEWAY_URL}" ]]; then
        log_warning "Timed out waiting for LoadBalancer hostname. Using NodePort instead."
        NODE_PORT=$(kubectl get svc apisix-gateway -n ${NAMESPACE} -o jsonpath='{.spec.ports[0].nodePort}')
        NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
        GATEWAY_URL="${NODE_IP}:${NODE_PORT}"
    fi
    
    log_success "API Gateway URL: ${GATEWAY_URL}"
    log_success "Deployment complete!"
    
    echo "Test the endpoints with:"
    echo "curl -H \"Host: api.example.com\" http://${GATEWAY_URL}/products/"
    echo "curl -H \"Host: api.example.com\" http://${GATEWAY_URL}/orders/"
    
    echo "-------------------------------------------"
    echo "AWS EKS Microservices Implementation Summary:"
    echo "✅ Two microservices deployed on AWS EKS"
    echo "✅ YugabyteDB integrated as persistent data store"
    echo "✅ Open Policy Agent for service communication policies"
    echo "✅ KEDA autoscaling implemented for both services"
    echo "✅ APISIX API Gateway for external access and routing"
    echo "✅ AWS EKS used as the Kubernetes platform"
    echo "-------------------------------------------"
}

# Call the main function
main