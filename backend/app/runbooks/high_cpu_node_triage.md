---
name: High CPU Node Triage
trigger: node high cpu, node cpu pressure, node struggling with load, cpu usage spike on node
---

## High CPU Node Triage

Goal: Identify CPU hogs on a node and potentially drain the node.

### Steps

1. **Check Node Status & Capacity** — Verify the node's condition and allocated CPU versus capacity. Use `get_node_status` and `get_node_capacity`.

2. **List Pods on Node** — Identify which pods are scheduled on this node to find the culprits. Use `list_pods_on_node`.

3. **Cordon or Drain** — If the node is overwhelmed and unstable, propose cordoning or draining it to migrate workloads. Use `cordon_node` or `drain_node`. Always ask the user for permission before cordoning or draining.

### Escalate If

- Critical system daemonsets are crashing
- Node is NotReady and unrecoverable
