# Eval scenarios

One file per observed client failure. Each is a behaviour we have seen the
agent get wrong, expressed as assertions on the tool-call trace and the final
answer.

Adding one: reproduce the failure, capture the tool responses that were in play
into `cluster:`, and write the `expect:` block describing what should have
happened. A scenario that passes on the first try before any fix is either
wrong or not reproducing the failure.

Run: `cd backend && python -m evals.run`
