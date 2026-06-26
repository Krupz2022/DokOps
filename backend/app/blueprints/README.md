# Seed blueprints

YAML dropped here is imported into the DB on startup (and via **Re-seed** / `POST /api/v1/blueprints/reseed`). The **path encodes the assignment scope** — you don't assign in the UI, the folder does it:

```
common/<name>.yaml                + files/<source>   → ALL minions (fleet-wide base layer)
orgs/<org>/<name>.yaml            + files/<source>   → that org
groups/<org>/<group>/<name>.yaml  + files/<source>   → that group
minions/<minion-id>/<name>.yaml   + files/<source>   → that one minion
```

A minion's compiled blueprint merges these **global → org → group → minion** — later wins by resource `id`. So `common/` is the shared base everyone gets; anything org/group/minion defines with the same `id` overrides it.

## Sources (files referenced by `file` resources)

Put the file content in a sibling `files/` dir. Text is stored as-is; non-text (zips, archives) is auto-detected and stored binary. A `file` resource references it by name:

```yaml
resources:
  - id: bundle
    type: file
    path: /opt/ansible-bundle.zip
    source: ansible-bundle.zip   # ← backend/app/blueprints/common/files/ansible-bundle.zip
```

## Notes

- Seeding is **idempotent** — re-running updates by name, never duplicates.
- Unknown org/group names are skipped and logged; DokOps never auto-creates them.
- Startup never prunes (a not-yet-mounted folder can't wipe data). **Re-seed** does prune — a seeded blueprint whose YAML is gone is removed. UI-created blueprints are never pruned.

Full reference: [docs/features/blueprints.md](../../../docs/features/blueprints.md).
