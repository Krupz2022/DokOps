import { useEffect, lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes, Navigate, useNavigate, useLocation } from "react-router-dom";
import Login from "./pages/Login";
import Setup from "./pages/Setup";
import Register from "./pages/Register";
import AuthCallback from "./pages/AuthCallback";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Resources = lazy(() => import("./pages/Resources"));
const Topology = lazy(() => import("./pages/Topology"));
const Admin = lazy(() => import("./pages/Admin"));
const Audit = lazy(() => import("./pages/Audit"));
const Settings = lazy(() => import("./pages/Settings"));
const Info = lazy(() => import("./pages/Info"));
const Docs = lazy(() => import("./pages/Docs"));
const Runbooks = lazy(() => import("./pages/Runbooks"));
const Toolsets = lazy(() => import("./pages/Toolsets"));
const AIChats = lazy(() => import("./pages/AIChats"));
const KnowledgeBase = lazy(() => import("./pages/KnowledgeBase"));
const Integrations = lazy(() => import("./pages/Integrations"));
const IntegrationAzure = lazy(() => import("./pages/IntegrationAzure"));
const MCPServers = lazy(() => import("./pages/MCPServers"));
const Workflows = lazy(() => import("./pages/Workflows"));
const Minions = lazy(() => import("./pages/Minions"));
const MinionDetail = lazy(() => import("./pages/MinionDetail"));
const Clusters = lazy(() => import("./pages/Clusters"));
const Vault = lazy(() => import("./pages/Vault"));
const Organisations = lazy(() => import("./pages/Organisations"));
const Patching = lazy(() => import("./pages/Patching"));
const Pipelines = lazy(() => import("./pages/Pipelines"));
const Schedules = lazy(() => import("./pages/Schedules"));
const AlertIncidents = lazy(() => import("./pages/AlertIncidents"));
const Analytics = lazy(() => import("./pages/Analytics"));

import { ThemeProvider } from "./components/ui/ThemeProvider";
import { AppProvider, useAppContext } from "./context/AppContext";
import { ChatProvider } from "./context/ChatContext";
import { ChatPanel } from "./components/ai/ChatPanel";
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
                                    <Suspense fallback={null}>
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
                                    </Suspense>
                                </StartupGuard>
                            </BrowserRouter>
                            {/* Global chat panel — persists across all route navigations */}
                            <ChatPanel />
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
