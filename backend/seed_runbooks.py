import os
import sys

# Add backend directory to path so we can import app modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from app.services.runbook_service import runbook_service

runbooks = [
    {
        "id": "crashloopbackoff_triage",
        "name": "CrashLoopBackOff Triage",
        "version": "1.0",
        "trigger": "User mentions a pod is in CrashLoopBackOff or restarting constantly",
        "applies_to": "Pods",
        "goal": "Identify the root cause of the container crash and attempt a restart if safe.",
        "steps": [
            {
                "title": "Check Pod Status",
                "instructions": "Get the current state of the pod and its containers to confirm CrashLoopBackOff.",
                "tools": ["get_pod_status"]
            },
            {
                "title": "Check Previous Logs",
                "instructions": "Fetch the logs of the previous crashed container instance to see the fatal error.",
                "tools": ["get_pod_logs"]
            },
            {
                "title": "Check Pod Events",
                "instructions": "Review recent events for the pod (e.g., Liveness probe failures, OutOfMemory).",
                "tools": ["get_pod_events"]
            },
            {
                "title": "Evaluate and Restart",
                "instructions": "If it was a transient error (e.g., failed to connect to DB once), propose a restart.",
                "tools": ["restart_pod"],
                "branches": [
                    {
                        "condition": "Error looks transient",
                        "action": "Restart the pod to see if it recovers",
                        "tool": "restart_pod"
                    }
                ]
            }
        ],
        "escalation_criteria": [
            "Application code is panicking due to a known bug",
            "Missing secret or configmap that you cannot fix"
        ],
        "principles": [
            "Always check 'previous=True' logs for CrashLoopBackOff"
        ]
    },
    {
        "id": "oomkilled_triage",
        "name": "OOMKilled Triage",
        "version": "1.0",
        "trigger": "User mentions a pod is OOMKilled or running out of memory",
        "applies_to": "Pods, Deployments",
        "goal": "Verify the OOMKilled status, check memory limits, and propose a resource patch.",
        "steps": [
            {
                "title": "Confirm OOMKilled Status",
                "instructions": "Check the pod status specifically looking for OOMKilled in the LastState or CurrentState.",
                "tools": ["get_pod_status"]
            },
            {
                "title": "Analyze Node Capacity",
                "instructions": "Check if the node itself is under memory pressure or just the pod limit was hit.",
                "tools": ["get_node_capacity"]
            },
            {
                "title": "Propose Memory Limit Increase",
                "instructions": "If the pod hit its limit but the node has capacity, propose patching the deployment with higher limits.",
                "tools": ["patch_deployment_resources"],
                "branches": [
                    {
                        "condition": "Pod memory limit needs to be increased",
                        "action": "Patch the deployment memory limit",
                        "tool": "patch_deployment_resources"
                    }
                ]
            }
        ],
        "escalation_criteria": [
            "Node is completely out of memory",
            "Memory leak in application requiring a code fix"
        ]
    },
    {
        "id": "pod_pending_triage",
        "name": "Pod Pending Triage",
        "version": "1.0",
        "trigger": "User mentions a pod is stuck in Pending state",
        "applies_to": "Pods",
        "goal": "Determine why the scheduler cannot place the pod on a node.",
        "steps": [
            {
                "title": "Check Pod Events",
                "instructions": "Events will usually say 'FailedScheduling'. Look for reasons like insufficient CPU/Memory or node selector mismatches.",
                "tools": ["get_pod_events"]
            },
            {
                "title": "Check Scheduling Constraints",
                "instructions": "Review the pod's nodeSelectors, affinities, and resource requests.",
                "tools": ["describe_pod_scheduling"]
            },
            {
                "title": "Check PVC Status",
                "instructions": "If the pod is waiting for a volume, check the PVC status.",
                "tools": ["get_pvc_status"]
            }
        ],
        "escalation_criteria": [
            "Cluster needs to be manually scaled up (add more nodes)",
            "Required storage class is not available"
        ]
    },
    {
        "id": "high_cpu_node_triage",
        "name": "High CPU Node Triage",
        "version": "1.0",
        "trigger": "User mentions a node has high CPU usage or is struggling with load",
        "applies_to": "Nodes",
        "goal": "Identify CPU hogs on a node and potentially drain the node.",
        "steps": [
            {
                "title": "Check Node Status & Capacity",
                "instructions": "Verify the node's condition and allocated CPU versus capacity.",
                "tools": ["get_node_status", "get_node_capacity"]
            },
            {
                "title": "List Pods on Node",
                "instructions": "Identify which pods are scheduled on this node to find the culprits.",
                "tools": ["list_pods_on_node"]
            },
            {
                "title": "Cordon or Drain",
                "instructions": "If the node is overwhelmed and unstable, propose cordoning or draining it to migrate workloads.",
                "tools": ["cordon_node", "drain_node"],
                "branches": [
                    {
                        "condition": "Node is very unstable",
                        "action": "Cordon the node",
                        "tool": "cordon_node"
                    }
                ]
            }
        ],
        "escalation_criteria": [
            "Critical system daemonsets are crashing",
            "Node is NotReady and unrecoverable"
        ]
    },
    {
        "id": "high_memory_node_triage",
        "name": "High Memory Node Triage",
        "version": "1.0",
        "trigger": "User mentions a node has high memory usage or MemoryPressure condition",
        "applies_to": "Nodes",
        "goal": "Identify memory pressure on the node and stabilize it.",
        "steps": [
            {
                "title": "Check Node Conditions",
                "instructions": "Look for the MemoryPressure condition on the node.",
                "tools": ["get_node_status", "get_node_capacity"]
            },
            {
                "title": "Prevent New Pods",
                "instructions": "Cordon the node to prevent the scheduler from adding more memory-intensive workloads to it.",
                "tools": ["cordon_node"]
            }
        ],
        "escalation_criteria": [
            "Kubelet is restarting due to memory starvation"
        ]
    },
    {
        "id": "service_unreachable_triage",
        "name": "Service Unreachable Triage",
        "version": "1.0",
        "trigger": "User mentions a service is unreachable, timeout, or 502/503 errors",
        "applies_to": "Deployments, Services",
        "goal": "Verify if the backing deployment is healthy and if endpoints exist.",
        "steps": [
            {
                "title": "Check Deployment Status",
                "instructions": "Verify the deployment has available replicas and is not failing its rollout.",
                "tools": ["get_deployment_status"]
            },
            {
                "title": "Inspect Pods",
                "instructions": "Check if the deployment's pods are actually running or in a crash loop.",
                "tools": ["get_pod_status", "get_pod_events"]
            },
            {
                "title": "Rollback if Recent Change",
                "instructions": "If a recent rollout broke the service, propose a rollback.",
                "tools": ["get_deployment_rollout_history", "rollback_deployment"],
                "branches": [
                    {
                        "condition": "Recent rollout is failing",
                        "action": "Rollback the deployment to the previous revision",
                        "tool": "rollback_deployment"
                    }
                ]
            }
        ],
        "escalation_criteria": [
            "Network Policy blocking traffic",
            "Ingress controller issues"
        ]
    }
]

import yaml

def main():
    print("Seeding runbooks...")
    for rb in runbooks:
        runbook_id = rb.pop("id")
        content = yaml.dump(rb, sort_keys=False)
        success = runbook_service.save_runbook(runbook_id, content)
        if success:
            print(f"Successfully seeded {runbook_id}")
        else:
            print(f"Failed to seed {runbook_id}")

if __name__ == "__main__":
    main()
