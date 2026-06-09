---
name: CrashLoopBackOff Triage
trigger: pod crashloopbackoff, pod restarting constantly, container keeps crashing
---

## CrashLoopBackOff Triage

Goal: Identify the root cause of the container crash and attempt a restart if safe.

### Steps

1. **Check Pod Status** — Get the current state of the pod and its containers to confirm CrashLoopBackOff. Use `get_pod_status`.

2. **Check Previous Logs** — Fetch the logs of the *previous* crashed container instance (`previous=True`) to see the fatal error. Use `get_pod_logs`.

3. **Check Pod Events** — Review recent events for the pod (e.g., Liveness probe failures, OutOfMemory). Use `get_pod_events`.

4. **Evaluate and Restart** — If the error looks transient (e.g., failed to connect to DB once), propose a pod restart using `restart_pod`. Ask the user for permission before restarting.

### Escalate If

- Application code is panicking due to a known bug
- Missing secret or configmap that you cannot fix

### Principles

- Always check `previous=True` logs for CrashLoopBackOff
