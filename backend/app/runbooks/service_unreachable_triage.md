---
name: Service Unreachable Triage
trigger: service unreachable, service timeout, 502 error, 503 error, service not responding
---

## Service Unreachable Triage

Goal: Verify if the backing deployment is healthy and if endpoints exist.

### Steps

1. **Check Deployment Status** — Verify the deployment has available replicas and is not failing its rollout. Use `get_deployment_status`.

2. **Inspect Pods** — Check if the deployment's pods are actually running or in a crash loop. Use `get_pod_status` and `get_pod_events`.

3. **Rollback if Recent Change** — If a recent rollout broke the service, propose a rollback using `rollback_deployment`. Ask the user for permission before rolling back.

### Escalate If

- Network Policy blocking traffic
- Ingress controller issues
