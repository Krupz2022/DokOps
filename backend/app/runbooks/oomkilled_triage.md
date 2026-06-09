---
name: OOMKilled Triage
trigger: pod oomkilled, pod out of memory, container killed by oom, memory limit exceeded
---

## OOMKilled Triage

Goal: Verify the OOMKilled status, check memory limits, and propose a resource patch.

### Steps

1. **Confirm OOMKilled Status** — Check the pod status specifically looking for OOMKilled in the LastState or CurrentState. Use `get_pod_status`.

2. **Analyze Node Capacity** — Check if the node itself is under memory pressure or just the pod limit was hit. Use `get_node_capacity`.

3. **Propose Memory Limit Increase** — If the pod hit its limit but the node has capacity, propose patching the deployment with higher limits using `patch_deployment_resources`. Ask the user for approval before applying.

### Escalate If

- Node is completely out of memory
- Memory leak in application requiring a code fix
