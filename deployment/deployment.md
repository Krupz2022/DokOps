# DokOps Deployment Guide

This guide describes how to deploy DokOps using Docker Compose.

## 1. Prerequisites
- Docker Engine & Docker Compose installed.
- (Optional) A `~/.kube/config` file if you want to pre-load local clusters.

## 2. Directory Structure
```
/project-root
  /backend
    Dockerfile
    requirements.txt
    ...
  /frontend
    Dockerfile
    nginx.conf
    ...
  /deployment
    docker-compose.yml
    deployment.md
```

## 3. Running with Docker Compose

1. Navigate to the `deployment` directory:
   ```bash
   cd deployment
   ```

2. Build and Start:
   ```bash
   docker-compose up --build -d
   ```

3. Access the application:
   - **Frontend**: [http://localhost:3000](http://localhost:3000)
   - **Backend**: [http://localhost:8000/docs](http://localhost:8000/docs)

## 4. Configuration
- **Backend**: Port `8000`. Mounts `~/.kube/config` by default.
- **Frontend**: Port `3000` (mapped to `80` internal). Proxies `/api/` to backend.

## 5. Alternative: Kubernetes Deployment
If you already have a Kubernetes cluster, use the standard microservices approach:

```bash
kubectl apply -f deployment/kubernetes.yaml
```
*Note: You will need to build and push the images (`dokops-backend`, `dokops-frontend`) to a registry accessible by your cluster first.*

## 6. Alternative: Single "Fat" Image
If you prefer a single artifact (e.g., for simple sharing or running on a VM without Compose), use the Standalone Dockerfile.

**Build:**
```bash
docker build -f deployment/Dockerfile.standalone -t dokops-aio .
```

**Run:**
```bash
docker run -p 3000:3000 -v ~/.kube/config:/root/.kube/config dokops-all-in-one
```
This runs Nginx (Frontend) and Uvicorn (Backend) inside the **same container**. It's great for simplicity but harder to scale horizontally.
