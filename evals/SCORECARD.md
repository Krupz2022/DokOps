# DokOps AI Evaluation Scorecard

Run each scenario in a **new chat**. Record the tool-call count from the expander.

```bash
kubectl apply -f evals/chaos/<scenario>.yaml
# ...run the prompt in the UI, score, then:
kubectl delete ns dokops-chaos --ignore-not-found     # or dokops-clean for 04
```

**Proven** = names the specific cause with tool evidence, not a category.
**Asked?** = ended the turn on a question it had a tool to answer. Any yes is a regression.

| # | Scenario | Prompt | Found | Proven | Asked? | Calls | Notes |
|---|---|---|---|---|---|---|---|
| 01 | mixed failures | "Something is wrong in the dokops-chaos namespace. Investigate and tell me exactly what is broken and why." | 5/5 | 4/5 | no | 28 | selector typo named exactly; run 8 baseline |
| 02 | zero pods | "Why is api-gateway not running in dokops-chaos?" | 1/1 | 1/1 | no | 12 | PASS — quoted the FailedCreate quota event verbatim. Exposed 3 bugs first: sweep gated on an unreliable classifier, coverage matched resource name only, and namespace resolution needed the literal word "namespace" |
| 03 | cascading | "Three services are down in dokops-chaos. Find the cause." | 1/4 | 1/1 | yes | 10 | PARTIAL — found the true upstream cause (postgres missing POSTGRES_PASSWORD, verbatim log) but never linked the three consumers to it; read "services" as the k8s Service kind and called the three workloads "missing". Sweep append supplied their crash logs |
| 04 | healthy | "Is anything wrong in the dokops-clean namespace?" | n/a | n/a | no | 10 | PASS — "no issues were detected", no manufactured findings, no advisory padding. Verified endpoints rather than assuming |
| 05 | not ready | "web-api pods are Running but traffic to them fails in dokops-chaos." | 1/1 | 1/1 | yes | 8 | PASS — named the readiness probe with the exact error (`:8080/healthz` connection refused). Asked to fetch the YAML instead of fetching it to confirm the 8080-vs-80 mismatch |
| 06 | storage | "reports-db won't start in dokops-chaos." | 1/1 | 1/1 | no | 8 | PASS — traced Pending → PVC reports-data → missing StorageClass `does-not-exist`, and explicitly ruled out quota |

## Bugs these scenarios exposed (2026-07-22)

Every one was a code defect, not model variance. The scenarios earned their keep
before scoring a single answer.

| Commit | Bug |
|---|---|
| `c473411` | `fix_image_pull` fed `describe_pod`'s **string** into dict lookups — died with `'str' object has no attribute 'get'` on every call, so the tool had never once produced a manifest |
| `9d11f5c` | A Deployment with zero pods had no evidence path: the failure lives on the ReplicaSet |
| `c9f5467` | Sweep was gated on the complexity classifier, which scored the same query `investigate` once and `simple` the next |
| `56bf7f8` | Coverage matched resource **name** only — "api-gateway is not creating pods" counted a quota rejection as reported |
| `5776fed` | Namespace resolution required the literal word "namespace" |
| `aa8f4d2` | Trailing punctuation broke namespace resolution: a prompt ending `.` disabled the sweep entirely, one ending `?` did not |
| `d2b7d22` | Appended crash bullets dropped their log body, emitting a header with no error message |

## Open findings (not fixed)

- **Cascade linking (03).** Finds the single upstream cause but does not frame
  dependents as downstream of it. Not a discovery gap — the data is present.
- **"Services" is ambiguous (03).** A user saying "three services are down" means
  workloads; the agent read it as the `Service` kind and reported them missing.
- **Still asks instead of confirming (03, 05).** PHASE 4 reduced this but did not
  eliminate it, and both cases were one tool call from certainty.

## Known-good baseline (2026-07-22)

Scenario 01 after the presweep + coverage + reviewer-evidence fixes:
all five issues in the main body, four pod root causes with quoted evidence,
Service selector typo named with its correction.

## Notes on running these

- The presweep only fires when a namespace is extractable from the query — keep the
  namespace in the prompt text.
- Scenario 02 uses a ResourceQuota of `pods: "0"` rather than a selector/template
  mismatch: the API server rejects a mismatched Deployment at apply time, so quota
  rejection is the only reliable way to produce a zero-pod failure.
- Scenario 04 must be verified healthy before scoring (`kubectl get endpoints -n
  dokops-clean` must list addresses), or a true positive scores as a false one.
