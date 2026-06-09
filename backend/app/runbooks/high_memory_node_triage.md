---
name: High Memory Node Triage
trigger: node high memory, node memory pressure, node memorypressure condition, node running out of memory
---

## High Memory Node Triage

Goal: Identify memory pressure on the node and stabilize it.

### Steps

1. **Check Node Conditions** — Look for the MemoryPressure condition on the node. Use `get_node_status` and `get_node_capacity`.

2. **Prevent New Pods** — Cordon the node to prevent the scheduler from adding more memory-intensive workloads to it. Use `cordon_node`. Ask the user for permission before cordoning.

### Escalate If

- Kubelet is restarting due to memory starvation
