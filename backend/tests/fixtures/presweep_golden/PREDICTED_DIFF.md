# Predicted golden diff — coverage extension

Two intended changes. Any changed line not attributable to one of them is a regression.

This prediction was derived by invoking the UNMODIFIED `_rollout_state` directly
against each scenario's exact fixture data (see verification below), before writing
or changing any production code. It corrects two errors in the task brief's own
illustrative Step 1 text — see "Divergence from the brief" at the bottom.

## 1. ImagePullBackOff / ErrImagePull added to _BLOCKED_REASONS

Effect: pods waiting with those reasons now appear under
"Containers blocked before start (no logs exist — the event is the evidence):".

Affected goldens: image_pull_backoff.txt (NEW scenario — new file, all lines added).
Existing goldens affected: NONE. No current scenario has a pod in ImagePullBackOff
or ErrImagePull.

## 2. _rollout_state wired into build_presweep

Placement: immediately after `sections = _render_sections(findings)` and BEFORE the
`if not sections: return ""` early-return check (per the task's ambiguity-resolution
note). Consequence for that ordering choice: a namespace whose *only* problem is a
failed/progressing rollout would now be reported instead of returning "". None of
the current fixtures actually hit this case (see empty_namespace below), so the
choice is inert for this diff, but it is the reason empty_namespace.txt is verified
to stay silent below rather than assumed to.

Effect: a new trailing section when the verdict is "failed" or "progressing".
Header: "Rollout state: <verdict>" followed by its existing pre-formatted bullet
lines (one line == one bullet here in every affected fixture, so the section is
always header + N bullets = N+1 added lines; every affected fixture below has
exactly one bullet, i.e. +2 lines each).

`_rollout_state`'s pod loop checks EVERY pod's container statuses for a
`_FATAL_WAITING` reason unconditionally — that check does not require the pod to
be owned by a Deployment/StatefulSet/DaemonSet. Only the separate "bare pod phase"
check (Failed / not-Ready) is gated on a missing owner_references. This means any
scenario whose fixture pod is sitting in CrashLoopBackOff (or another
_FATAL_WAITING reason) picks up a fatal rollout line even with zero Deployments
in the fixture.

Verified per-scenario by calling `_rollout_state(core, apps, "dokops-chaos")`
directly against each scenario's own fixture construction, unmodified:

| scenario                         | verdict     | rollout line                                              | golden effect |
|-----------------------------------|-------------|-------------------------------------------------------------|---------------|
| crashloop_oom                     | failed      | `  - checkoutapi-vw2m5/checkoutapi: CrashLoopBackOff`        | +2 lines |
| crashloop_plain                   | failed      | `  - order-worker-qz/worker: CrashLoopBackOff`               | +2 lines |
| blocked_configmap                 | failed      | `  - notify-svc-x/app: CreateContainerConfigError`           | +2 lines |
| no_previous_log                   | failed      | `  - api-xyz/app: CrashLoopBackOff`                          | +2 lines |
| replicaset_quota_failure          | progressing | `  - deployment/api: 0/1 ready`                              | +2 lines |
| zero_endpoint_selector_mismatch   | healthy     | (none)                                                       | NO CHANGE |
| zero_endpoint_no_selector         | healthy     | (none)                                                       | NO CHANGE |
| deployment_scaled_to_zero         | healthy     | (none — desired 0 not counted unready)                       | NO CHANGE |
| collector_raises_deployments      | raises inside `_rollout_state` (apps.list_namespaced_deployment side_effect), caught by the new try/except | — | NO CHANGE |
| collector_raises_pod_listing      | raises inside `_rollout_state` (core.list_namespaced_pod side_effect), caught by the new try/except | — | NO CHANGE |
| empty_namespace                   | healthy     | (none)                                                       | NO CHANGE — stays 0 bytes: sections is already empty when the rollout block runs, verdict is healthy so nothing is appended, `if not sections: return ""` still fires |
| config_sources_with_resources     | n/a — exercises `build_config_sources`, never calls `build_presweep`/`_rollout_state` | — | NO CHANGE |
| image_pull_backoff (NEW)          | failed      | `  - api-abc/app: ImagePullBackOff`                          | new file — combines with effect 1 (blocked-container section) |

## Divergence from the brief's illustrative Step 1 text

The brief's own Step 1 example text predicted only `replicaset_quota_failure.txt`
would be touched by effect 2, with verdict "failed", and stated
`crashloop_oom.txt : NO CHANGE (no Deployment in fixture)` plus "all others: NO
CHANGE". Both are wrong, verified against the unmodified code before any change:

- `replicaset_quota_failure`'s fixture has no pods and its Deployment has no
  `ProgressDeadlineExceeded` condition, so `_rollout_state` classifies it as
  **"progressing"**, not "failed" — the deployment being under-ready alone is not
  a fatal signal. The `+2` line count the brief predicted is still correct; only
  the verdict word is wrong.
- The brief's "no Deployment in fixture" reasoning for `crashloop_oom` conflates
  "no Deployment" with "rollout check doesn't apply". It does apply: the pod-level
  fatal-waiting-reason check runs against every pod's container statuses
  regardless of whether that pod is Deployment-owned. `crashloop_oom`,
  `crashloop_plain`, `blocked_configmap`, and `no_previous_log` all have a fixture
  pod parked in `CrashLoopBackOff` or `CreateContainerConfigError` (both in
  `_FATAL_WAITING`), so all four gain a "Rollout state: failed" section.

This document's table above supersedes the brief's Step 1 text and is the
prediction this task's diff gate is checked against.

## Assertion

Regenerated goldens will differ from committed goldens ONLY in:
  - one new file `image_pull_backoff.txt`
  - exactly `+2` lines each in: `crashloop_oom.txt`, `crashloop_plain.txt`,
    `blocked_configmap.txt`, `no_previous_log.txt`, `replicaset_quota_failure.txt`

Everything else byte-identical. Any other changed line is a regression — stop and
investigate; do not accept it because a diff was expected.
