# Cluster Topology

The Topology page shows an interactive force-directed graph of your cluster's dependency relationships. It helps you understand what depends on what before making changes, and calculates **blast radius** — everything that would be affected if a resource is removed.

---

## Opening the Topology Graph

1. Click **Topology** in the sidebar.
2. The graph loads live from your cluster. For large clusters this may take a few seconds.
3. The graph auto-arranges using a physics simulation. Nodes repel each other and links pull related nodes together.

---

## Node Types

Each node type has a distinct color and icon:

| Color | Resource Type | Description |
|-------|--------------|-------------|
| Blue | **Pod** | Running pod instance |
| Teal | **Service** | ClusterIP/LoadBalancer/NodePort service |
| Orange | **Ingress** | HTTP ingress rule pointing to services |
| Purple | **ConfigMap** | Configuration data mounted by pods |
| Amber | **PersistentVolumeClaim** | Persistent storage claimed by pods |
| Grey | **Node** | Worker node where pods are scheduled |

---

## Dependency Edges

Edges represent actual relationships derived from Kubernetes selectors and specs:

| Edge | Relationship |
|------|-------------|
| Service → Pod | Service selector matches pod labels |
| Ingress → Service | Ingress backend rule targets the service |
| Pod → ConfigMap | Pod volume mount or envFrom references the ConfigMap |
| Pod → PVC | Pod volume references the PVC |
| Pod → Node | Pod is scheduled on the node |

---

## Interacting with the Graph

### Pan and Zoom
- **Scroll** to zoom in/out.
- **Click + drag** on empty space to pan.

### Select a Node
- **Click** a node to open the **Detail Drawer** on the right.

### Filter by Namespace
- Use the namespace selector above the graph to show only resources from one namespace.

### Controls
- **Reset Layout** — re-run the physics simulation (useful if nodes overlap)
- **Fit to Screen** — zoom to fit all nodes
- **Toggle Labels** — show/hide node name labels

---

## Node Detail Drawer

When you click a node, the Detail Drawer shows:

**For Pods:**
- Status, image, node placement
- CPU and memory usage
- Connected services (which services route to this pod)
- Mounted ConfigMaps and PVCs
- **Blast Radius** — if this pod is removed, which services lose all endpoints?

**For Services:**
- Port mapping, type, cluster IP
- Matching pods (by selector)
- **Blast Radius** — which Ingresses route through this service?

**For Nodes:**
- CPU and memory capacity and usage
- Number of pods scheduled
- Conditions (Ready, MemoryPressure, DiskPressure)

---

## Blast Radius

The Detail Drawer shows a **Blast Radius** section. This tells you the downstream impact of removing or failing the selected resource.

Example for a Service `payments-svc`:

```
Blast Radius for: payments-svc (Service)
├── Ingress: payments-ingress
│   └── (traffic to /api/payments/* will fail)
├── Pods routing through this service: 3
│   ├── payments-api-6d9f7b-abc
│   ├── payments-api-6d9f7b-def
│   └── payments-api-6d9f7b-ghi
```

---

## Topology in AI Chat

The AI can use the topology graph during diagnostics. Ask:

```
"What would break if I delete the payments-svc service?"

AI: [Step] Fetching topology for 'payments-svc' in namespace 'production'...

    Blast radius analysis:
    - Ingress 'payments-ingress' routes /api/payments to this service.
      Traffic to /api/payments would return 502.
    - 3 pods currently receive traffic through this service.
    - Downstream: the 'checkout' service calls payments via this Ingress.
      The entire checkout flow would be affected.
```

---

## Performance Notes

- Topology is built from live Kubernetes API calls. For clusters with 500+ pods, the initial load may take 5–10 seconds.
- The background topology service refreshes the graph every 60 seconds.
- You can force a refresh by navigating away from and back to the Topology page.
