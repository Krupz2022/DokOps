import axios from "axios";

const api = axios.create({
    baseURL: import.meta.env.VITE_API_URL || "/api/v1",
    withCredentials: true,
});

api.interceptors.request.use((config) => {
    // Use localStorage token as fallback for existing sessions until cookie is set
    const token = localStorage.getItem("access_token");
    const clusterContext = localStorage.getItem("clusterContext");
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    if (clusterContext) {
        config.headers["X-Cluster-Context"] = clusterContext;
    }
    return config;
});

// Handle 401 Unauthorized errors by redirecting to login
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            // Clear invalid token and redirect to login
            localStorage.removeItem("access_token");
            window.location.href = "/login";
        }
        return Promise.reject(error);
    }
);

export default api;

import type { Workflow, WorkflowCreate, WorkflowRun, JiraFieldSchema, JiraUser, JiraCredentials } from "../types/workflow";

export const workflowApi = {
  list: () => api.get<Workflow[]>("/workflows"),
  create: (data: WorkflowCreate) => api.post<Workflow>("/workflows", data),
  get: (id: number) => api.get<Workflow>(`/workflows/${id}`),
  update: (id: number, data: Partial<WorkflowCreate>) => api.put<Workflow>(`/workflows/${id}`, data),
  delete: (id: number) => api.delete(`/workflows/${id}`),
  run: (id: number, input: Record<string, unknown>) =>
    api.post<{ run_id: number; status: string }>(`/workflows/${id}/run`, { input }),
  getRun: (runId: number) => api.get<WorkflowRun>(`/workflows/runs/${runId}`),
  listRuns: (workflowId: number) => api.get<WorkflowRun[]>(`/workflows/${workflowId}/runs`),
  streamUrl: (runId: number, ticket?: string) => {
    const base = import.meta.env.VITE_API_URL || "/api/v1";
    const url = `${base}/workflows/runs/${runId}/stream`;
    return ticket ? `${url}?ticket=${encodeURIComponent(ticket)}` : url;
  },
  issueStreamTicket: (runId: number) =>
    api.post<{ ticket: string }>(`/workflows/runs/${runId}/stream-ticket`),
};

export const jiraApi = {
  getFields: (body: JiraCredentials & { project_key: string; issue_type: string }) =>
    api.post<JiraFieldSchema[]>("/workflows/connectors/jira/fields", body),

  getIssueTypes: (body: JiraCredentials & { project_key: string }) =>
    api.post<string[]>("/workflows/connectors/jira/issue-types", body),

  searchUsers: (body: JiraCredentials & { query: string }) =>
    api.post<JiraUser[]>("/workflows/connectors/jira/users/search", body),
};
