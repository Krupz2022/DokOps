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
| 03 | cascading | "Three services are down in dokops-chaos. Find the cause." | | | | | fail = 4 coequal findings |
| 04 | healthy | "Is anything wrong in the dokops-clean namespace?" | n/a | n/a | | | must find NOTHING |
| 05 | not ready | "web-api pods are Running but traffic to them fails." | | | | | |
| 06 | storage | "reports-db won't start in dokops-chaos." | | | | | |

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
