import React, { createContext, useContext, useState, useEffect } from "react";
import api from "../lib/api";
import { useToast } from "./ToastContext";

interface AppContextType {
    godModeActive: boolean;
    isSuperuser: boolean;
    toggleGodMode: () => Promise<void>;
    refreshUser: () => void;
    loading: boolean;
    setupComplete: boolean;
    signupEnabled: boolean;
    ssoEnabled: boolean;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
    const [godModeActive, setGodModeActive] = useState(false);
    const [isSuperuser, setIsSuperuser] = useState(false);
    const [loading, setLoading] = useState(true);
    const [setupComplete, setSetupComplete] = useState(false);
    const [signupEnabled, setSignupEnabled] = useState(false);
    const [ssoEnabled, setSsoEnabled] = useState(false);

    const { toast } = useToast();

    useEffect(() => {
        const fetchInitialState = async () => {
            try {
                const res = await api.get("/system/status");
                setGodModeActive(res.data.god_mode_active ?? false);
                setSetupComplete(res.data.setup_complete);
                setSignupEnabled(res.data.signup_enabled);
                setSsoEnabled(res.data.sso_enabled ?? false);
                setIsSuperuser(res.data.is_superuser ?? false);
            } catch (err) {
                console.error("Failed to fetch app state", err);
            } finally {
                setLoading(false);
            }
        };

        fetchInitialState();
    }, []);

    const refreshUser = () => {
        const userStr = localStorage.getItem("user");
        if (userStr) {
            const user = JSON.parse(userStr);
            setIsSuperuser(!!user.is_superuser);
        }
    };

    const toggleGodMode = async () => {
        try {
            const newMode = godModeActive ? "NORMAL" : "GOD";
            await api.post("/system/mode", { mode: newMode });
            setGodModeActive(!godModeActive);
        } catch (err) {
            console.error("Failed to toggle mode", err);
            toast("Failed to change mode. Ensure you are admin.", "error");
        }
    };

    return (
        <AppContext.Provider value={{
            godModeActive, isSuperuser, toggleGodMode,
            refreshUser, loading, setupComplete, signupEnabled, ssoEnabled,
        }}>
            {children}
        </AppContext.Provider>
    );
}

export function useAppContext() {
    const context = useContext(AppContext);
    if (!context) {
        throw new Error("useAppContext must be used within an AppProvider");
    }
    return context;
}
