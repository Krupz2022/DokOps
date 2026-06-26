# Organisations

Organisations and groups are how you **organize your minions** into a tidy hierarchy — an Org (e.g. a company or department) contains Groups (e.g. "web servers", "databases"), and minions belong to a group.

> **Shared notes:**
> - Reading is allowed for any logged-in user.
> - **Creating, assigning, and deleting** orgs/groups/members require **God Mode**.

---

## GET /api/v1/organisations/

**What this does:** Lists all organisations.

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/organisations/
```

**Example response (200):** array of `{ "id": "org_1", "name": "Acme", "slug": "acme" }`.

---

## POST /api/v1/organisations/

**What this does:** Creates a new organisation.

**Auth required?** **God Mode required.**

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Display name. |
| `slug` | string | yes | Short URL-safe identifier (e.g. `acme`). |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/organisations/ \
  -d '{"name":"Acme","slug":"acme"}'
```

**Example response (200):** the created org object.

---

## GET /api/v1/organisations/{org_id}

**What this does:** Returns one organisation's details.

**Auth required?** Token. **Path:** `org_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/organisations/org_1
```

**Example response (200):** the org object.

**Common errors:** `404` not found.

---

## DELETE /api/v1/organisations/{org_id}

**What this does:** Deletes an organisation.

**Auth required?** **God Mode required.** **Path:** `org_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/organisations/org_1
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/organisations/{org_id}/assign

**What this does:** Moves a minion into a specific group within this org. (Only one group per org per minion is allowed.)

**Auth required?** **God Mode required.** **Path:** `org_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `minion_id` | string | yes | The minion to move. |
| `group_id` | string | yes | The destination group. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/organisations/org_1/assign \
  -d '{"minion_id":"m_12","group_id":"grp_3"}'
```

**Example response (200):** `{ "status": "assigned" }`

---

## GET /api/v1/organisations/groups

**What this does:** Lists **all** groups across all organisations (handy for dropdowns).

**Auth required?** Token.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/organisations/groups
```

**Example response (200):** array of `{ "id": "grp_3", "name": "web servers", "org_id": "org_1" }`.

---

## GET /api/v1/organisations/{org_id}/groups

**What this does:** Lists the groups inside one organisation.

**Auth required?** Token. **Path:** `org_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/organisations/org_1/groups
```

**Example response (200):** array of group objects for that org.

---

## POST /api/v1/organisations/{org_id}/groups

**What this does:** Creates a group inside an organisation.

**Auth required?** **God Mode required.** **Path:** `org_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Group name. |
| `description` | string | no | Optional description. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/organisations/org_1/groups \
  -d '{"name":"web servers","description":"All frontend nodes"}'
```

**Example response (200):** the created group object.

---

## GET /api/v1/organisations/groups/{group_id}

**What this does:** Returns one group's details (including its members).

**Auth required?** Token. **Path:** `group_id` (string, required).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/organisations/groups/grp_3
```

**Example response (200):** the group object with member minions.

---

## DELETE /api/v1/organisations/groups/{group_id}

**What this does:** Deletes a group.

**Auth required?** **God Mode required.** **Path:** `group_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/organisations/groups/grp_3
```

**Example response (200):** `{ "status": "deleted" }`

---

## POST /api/v1/organisations/groups/{group_id}/members

**What this does:** Adds a minion to a group.

**Auth required?** Token. **Path:** `group_id` (string, required).

**Request body** (JSON):

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `minion_id` | string | yes | The minion to add. |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/organisations/groups/grp_3/members \
  -d '{"minion_id":"m_12"}'
```

**Example response (200):** `{ "status": "added" }`

---

## DELETE /api/v1/organisations/groups/{group_id}/members/{minion_id}

**What this does:** Removes a minion from a group.

**Auth required?** **God Mode required.** **Path:** `group_id`, `minion_id` (string, required).

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/organisations/groups/grp_3/members/m_12
```

**Example response (200):** `{ "status": "removed" }`
