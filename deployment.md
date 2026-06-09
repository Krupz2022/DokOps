# DokOps-AIO Deployment Guide 🚀

This guide covers all supported deployment methods for the Autonomous DevOps Agent Platform.
**Prerequisite for all methods**: You must have a valid Kubernetes `config` file (usually at `~/.kube/config`) to mount or use.

---

## 1. Quick Start: Docker (Single Command) 🐳
The fastest way to run the platform locally.

```bash
docker run --rm -it \
  -p 3000:3000 \
  -p 8000:8000 \
  -v ~/.kube/config:/root/.kube/config \
  krupz/dokops-aio:latest
```
*Access UI at: [http://localhost:3000](http://localhost:3000)*

---

## 2. Docker Compose 🐙
For more permanent local setups or development.

**File:** `deployment/docker-compose.yml`
```yaml
version: '3.8'
services:
  dokops:
    image: krupz/dokops-aio:latest
    ports:
      - "3000:3000"
      - "8000:8000"
    volumes:
      - ~/.kube/config:/root/.kube/config:ro
```

**Run:**
```bash
cd deployment
docker-compose up -d
```

---

## 3. Kubernetes (Manifest) ☸️
For deploying INTO a cluster.

**File:** `deployment/k8s-manifest.yaml`

**Steps:**
1. **Create Secret** (for Auth):
    ```bash
    kubectl create secret generic dokops-aio-secrets --from-literal=auth-secret="your-secure-key"
    ```
2. **Apply Manifest**:
    ```bash
    kubectl apply -f deployment/k8s-manifest.yaml
    ```
3. **Access**:
    Get the LoadBalancer IP:
    ```bash
    kubectl get svc dokops-aio-service
    ```
    Or port-forward if using Minikube/local:
    ```bash
    kubectl port-forward svc/dokops-aio-service 3000:80
    ```

---

## 4. Helm Chart (Production) 🛡️
The recommended way for production deployments with versioning and rollbacks.

**Path:** `deployment/helm/dokops-aio`

**Steps:**
1. **Create Secret** (Same as above):
    ```bash
    kubectl create secret generic dokops-aio-secrets --from-literal=auth-secret="your-secure-key"
    ```
2. **Install / Upgrade**:
    ```bash
    helm upgrade --install dokops ./deployment/helm/dokops-aio \
      --namespace default \
      --set ingress.enabled=true \
      --set ingress.hosts[0].host=dokops.local
    ```

**Configuration (`values.yaml`):**
Key settings you might want to tweak:
*   `persistence.enabled`: Defaults to `true` (1Gi PVC).
*   `ingress.enabled`: Enable if using an Ingress Controller (Nginx, Traefik).
*   `image.tag`: Pin to specific version if needed.
