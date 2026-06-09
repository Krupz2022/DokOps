import { useEffect } from "react";
import { BrowserRouter, Route, Routes, Navigate, useNavigate, useLocation } from "react-router-dom";
import Login from "./pages/Login";
import Setup from "./pages/Setup";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Resources from "./pages/Resources";
import Topology from "./pages/Topology";
import Admin from "./pages/Admin";
import Audit from "./pages/Audit";
import Settings from "./pages/Settings";
import Info from "./pages/Info";
import Docs from "./pages/Docs";
import Runbooks from "./pages/Runbooks";
import Toolsets from "./pages/Toolsets";
import AIChats from "./pages/AIChats";
import KnowledgeBase from "./pages/KnowledgeBase";
import Integrations from "./pages/Integrations";
import IntegrationAzure from "./pages/IntegrationAzure";
import MCPServers from "./pages/MCPServers";
import AuthCallback from "./pages/AuthCallback";
import Workflows from "./pages/Workflows";
import Minions from "./pages/Minions";
import MinionDetail from "./pages/MinionDetail";
import Clusters from "./pages/Clusters";
import Vault from "./pages/Vault";
import Organisations from "./pages/Organisations";
import Patching from "./pages/Patching";
import Pipelines from "./pages/Pipelines";
import Schedules from "./pages/Schedules";
import AlertIncidents from "./pages/AlertIncidents";
import Analytics from "./pages/Analytics";

import { ThemeProvider } from "./components/ui/ThemeProvider";
import { AppProvider, useAppContext } from "./context/AppContext";
import { ChatProvider } from "./context/ChatContext";
import { AppLayout } from "./components/layout/AppLayout";
import { ToastProvider } from "./context/ToastContext";
import { ConfirmProvider } from "./context/ConfirmContext";
import { ToastContainer } from "./components/ui/ToastContainer";

/**
 * Redirects to /setup when no users exist yet,
 * or to /login when the user is not authenticated.
 * Runs after AppContext finishes its initial status fetch.
 */
function AdminGuard({ children }: { children: React.ReactNode }) {
    const { isSuperuser, loading } = useAppContext();
    if (loading) return null;
    if (!isSuperuser) return <Navigate to="/dashboard" replace />;
    return <>{children}</>;
}

function StartupGuard({ children }: { children: React.ReactNode }) {
    const { loading, setupComplete } = useAppContext();
    const navigate = useNavigate();
    const location = useLocation();

    useEffect(() => {
        if (loading) return;

        const setupBypassPaths = ["/setup", "/auth-callback"];
        if (!setupComplete && !setupBypassPaths.includes(location.pathname)) {
            navigate("/setup", { replace: true });
            return;
        }

        // If setup is complete but user landed on /setup, send them to login
        if (setupComplete && location.pathname === "/setup") {
            navigate("/login", { replace: true });
            return;
        }

        const publicPaths = ["/login", "/register", "/setup", "/auth-callback"];
        const hasToken = !!localStorage.getItem("access_token");
        if (setupComplete && !hasToken && !publicPaths.includes(location.pathname)) {
            navigate("/login", { replace: true });
        }
    }, [loading, setupComplete, location.pathname, navigate]);

    if (loading) return null;
    return <>{children}</>;
}

function App() {
    return (
        <ThemeProvider defaultTheme="light" storageKey="app-ui-theme">
            <ToastProvider>
                <ConfirmProvider>
                    <AppProvider>
                        <ChatProvider>
                            <BrowserRouter>
                                <StartupGuard>
                                    <Routes>
                                        <Route path="/login" element={<Login />} />
                                        <Route path="/setup" element={<Setup />} />
                                        <Route path="/register" element={<Register />} />
                                        <Route path="/dashboard" element={<AppLayout><Dashboard /></AppLayout>} />
                                        <Route path="/resources" element={<AppLayout><Resources /></AppLayout>} />
                                        <Route path="/clusters" element={<AppLayout><Clusters /></AppLayout>} />
                                        <Route path="/vault" element={<AppLayout><Vault /></AppLayout>} />
                                        <Route path="/topology" element={<AppLayout><Topology /></AppLayout>} />
                                        <Route path="/admin" element={<AdminGuard><AppLayout><Admin /></AppLayout></AdminGuard>} />
                                        <Route path="/audit" element={<AppLayout><Audit /></AppLayout>} />
                                        <Route path="/analytics" element={<AdminGuard><AppLayout><Analytics /></AppLayout></AdminGuard>} />
                                        <Route path="/settings" element={<AppLayout><Settings /></AppLayout>} />
                                        <Route path="/info" element={<AppLayout><Info /></AppLayout>} />
                                        <Route path="/docs" element={<AppLayout><Docs /></AppLayout>} />
                                        <Route path="/runbooks" element={<AppLayout><RunbooksPage /></AppLayout>} />
                                        <Route path="/toolsets" element={<AppLayout><Toolsets /></AppLayout>} />
                                        <Route path="/mcp-servers" element={<AppLayout><MCPServers /></AppLayout>} />
                                        <Route path="/ai-chats" element={<AppLayout><AIChats /></AppLayout>} />
                                        <Route path="/knowledge-base" element={<AppLayout><KnowledgeBase /></AppLayout>} />
                                        <Route path="/integrations" element={<AppLayout><Integrations /></AppLayout>} />
                                        <Route path="/integrations/azure" element={<AppLayout><IntegrationAzure /></AppLayout>} />
                                        <Route path="/workflows" element={<AppLayout><Workflows /></AppLayout>} />
                                        <Route path="/infrastructure/minions" element={<AppLayout><Minions /></AppLayout>} />
                                        <Route path="/infrastructure/minions/:minionId" element={<AppLayout><MinionDetail /></AppLayout>} />
                                        <Route path="/infrastructure/organisations" element={<AppLayout><Organisations /></AppLayout>} />
                                        <Route path="/patching" element={<AppLayout><Patching /></AppLayout>} />
                                        <Route path="/patching/pipelines" element={<AppLayout><Pipelines /></AppLayout>} />
                                        <Route path="/patching/schedules" element={<AppLayout><Schedules /></AppLayout>} />
                                        <Route path="/alerts" element={<AppLayout><AlertIncidents /></AppLayout>} />
                                        <Route path="/auth-callback" element={<AuthCallback />} />
                                        <Route path="/" element={<Navigate to="/dashboard" replace />} />
                                    </Routes>
                                </StartupGuard>
                            </BrowserRouter>
                        </ChatProvider>
                    </AppProvider>
                </ConfirmProvider>
                <ToastContainer />
            </ToastProvider>
        </ThemeProvider>
    );
}

function RunbooksPage() {
    return <Runbooks />;
}

export default App;
