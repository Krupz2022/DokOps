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

**Always-on core tools get a default even if you don't fixture them.**
`AIService._CORE_K8S` (app/services/ai_service.py) is injected into every
query's tool schema regardless of routing, so the model can reach for any of
those 17 names in a scenario that has nothing to do with Kubernetes. Calling
one is not a defect the scenario needs to catch by forbidding it -- see
`evals/defaults.py` and `harness._fixture_server`, which serve a plausible,
well-formed "nothing here" response for any of them you don't fixture,
instead of the "eval: no fixture" miss below. A `cluster:` fixture for one of
these still always wins over its default. Only forbid a core tool via
`must_not_call` when calling it would genuinely mean the agent misrouted the
question (e.g. reaching for `search_pods` to answer a database question) --
not merely because it's in the core set.

**Advisory checks never fail a scenario.** Some checks (`no_unknown_names`
today) are a shortlist for a human to read, not proof of a defect — they are
still computed and still printed in the console report and `last-run.json`
(under an `[advisory]` heading / `"advisory": true` field), but a failing
advisory check cannot flip a scenario's pass/fail verdict. Only non-advisory
checks feed the threshold in `run.py`. If you add a new check whose own
definition admits false positives are expected, mark it advisory rather than
letting it gate the verdict.

Run: `cd backend && python -m evals.run`
