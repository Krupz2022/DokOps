---
name: Pod Pending Triage
trigger: pod stuck pending, pod not starting, pod pending state, scheduler cannot place pod
---

## Pod Pending Triage

Goal: Determine why the scheduler cannot place the pod on a node.

### Steps

1. **Check Pod Events** — Events will usually say `FailedScheduling`. Look for reasons like insufficient CPU/Memory or node selector mismatches. Use `get_pod_events`.

2. **Check Scheduling Constraints** — Review the pod's nodeSelectors, affinities, and resource requests. Use `describe_pod_scheduling`.

3. **Check PVC Status** — If the pod is waiting for a volume, check the PVC status. Use `get_pvc_status`.

### Escalate If

- Cluster needs to be manually scaled up (add more nodes)
- Required storage class is not available
