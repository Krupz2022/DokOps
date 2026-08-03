# Eval scenarios

One file per observed client failure. Each is a behaviour we have seen the
agent get wrong, expressed as assertions on the tool-call trace and the final
answer.

Adding one: reproduce the failure, capture the tool responses that were in play
into `cluster:`, and write the `expect:` block describing what should have
happened. A scenario that passes on the first try before any fix is either
wrong or not reproducing the failure.

**A fixture must mirror what the real tool actually returns — read the
tool's implementation before writing one.** A fixture that is more
informative than production makes the eval measure fiction: the agent looks
competent because the fixture did its thinking for it. Two concrete ways
this goes wrong, both seen in this directory before being caught by review:

- **Wrong shape.** Several real k8s tools return a single formatted string
  (`describe_pod`, `diagnose_pod`, `diagnose_service`, `redis_info`,
  `apply_manifest` once confirmed) or a dict wrapped under a named key
  (`list_services` -> `{"services": [...], "total": N}`,
  `list_deployments` -> `{"deployments": [...], "count": N}`) — not a bare
  list or an ad hoc dict of whatever fields felt relevant when the fixture
  was written. Check the tool's function in `app/tools/*.py` (or the
  service it delegates to) for the exact return shape before fixturing it.
- **Leaked answer / fabricated capability.** A fixture must not contain a
  field or a conclusion the real tool cannot produce. `list_services` does
  not return a Service's selector — `get_resource_yaml` or a tool that
  reads the Service spec does. `diagnose_service`'s zero-endpoints finding
  states the endpoint count, never the selector value or a stated mismatch
  — the model has to reach for `get_resource_yaml`/`describe_pod` and derive
  the mismatch itself. If a fixture hands over the exact string a
  `must_cite` assertion checks for, before the tool call that's supposed to
  produce it, the scenario can pass without the behaviour under test ever
  happening.

**Advisory checks never fail a scenario.** Some checks (`no_unknown_names`
today) are a shortlist for a human to read, not proof of a defect — they are
still computed and still printed in the console report and `last-run.json`
(under an `[advisory]` heading / `"advisory": true` field), but a failing
advisory check cannot flip a scenario's pass/fail verdict. Only non-advisory
checks feed the threshold in `run.py`. If you add a new check whose own
definition admits false positives are expected, mark it advisory rather than
letting it gate the verdict.

**Known-failing scenarios are deliberately deferred, not silently ignored.**
`database-slow-oblique-phrasing` and `broker-dropping-messages-oblique-phrasing`
are marked `known_failing: true` and reported under a distinct `KNOWN` verdict,
excluded from the "N/M scenarios at or above threshold" headline in
`evals/run.py` — but never hidden; their detail still prints every run. Both
are mis-specified in the same way: the query deliberately names no engine
(that's the oblique-phrasing behaviour under test), yet `must_call_any`
demands one specific engine's tools (`postgres_*` / `rabbitmq_*`), and
`must_not_call` forbids the ordinary discovery tools (`search_topology`,
`list_services`, ...) a genuinely ambiguous complaint should be allowed to
reach for before picking a tool family. There is no namespace or instance
context in these scenarios to disambiguate what the model should do instead.
The routing gap they were meant to test — does the model fall back to
Kubernetes tools when a non-Kubernetes system is described obliquely — is
already covered deterministically by
`backend/tests/test_tool_discovery_pointer.py`, which does not depend on a
live LLM. `configmap-is-not-a-namespace` is a separate, ordinary flaky
scenario (not deferred) — it has scored 3/3 in other runs and stays under
the normal `PASS`/`FAIL` verdict.

Run: `cd backend && python -m evals.run`
