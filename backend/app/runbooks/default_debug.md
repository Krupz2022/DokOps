---
name: Default Debug
trigger: general debug, check pod, something is wrong, investigate issue, default troubleshoot
---

## Default Debug

Goal: Fetch events and logs to identify common startup or runtime failures.

### Steps

1. **Check Events** — Fetch recent events for the pod to spot scheduling or runtime issues. Use `get_pod_events`.

2. **Check Logs** — Fetch the pod logs to identify application-level errors. Use `get_pod_logs`.
