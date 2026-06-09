import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, Orbit } from "lucide-react";
import { useAppContext } from "../context/AppContext";

export default function AuthCallback() {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);
    const { refreshUser } = useAppContext();
    const completed = useRef(false);

    useEffect(() => {
        if (completed.current) return;
        completed.current = true;

        const token = searchParams.get("token");
        const username = searchParams.get("username");
        const role = searchParams.get("role");
        const isSuperuserRaw = searchParams.get("is_superuser");
        const returnedState = searchParams.get("state");

        // Validate OAuth state to prevent session fixation / CSRF
        const storedState = sessionStorage.getItem("sso_state");
        sessionStorage.removeItem("sso_state");
        if (storedState && returnedState !== storedState) {
            setError("Invalid OAuth state parameter. Please try logging in again.");
            return;
        }

        if (!token || !username) {
            setError("Missing SSO response parameters. Please try logging in again.");
            return;
        }

        localStorage.setItem("access_token", token);
        localStorage.setItem(
            "user",
            JSON.stringify({
                username: username,
                role: role ?? "",
                is_superuser: isSuperuserRaw === "true",
            })
        );

        refreshUser();
        navigate("/dashboard", { replace: true });
    }, [searchParams, navigate, refreshUser]);

    if (error) {
        return (
            <div className="flex h-screen bg-[#050810] items-center justify-center">
                <div
                    className="absolute inset-0 pointer-events-none"
                    style={{
                        backgroundImage:
                            "radial-gradient(circle, hsl(220 35% 18% / 0.6) 1px, transparent 1px)",
                        backgroundSize: "20px 20px",
                    }}
                />
                <div className="relative z-10 w-full max-w-sm px-6 text-center">
                    <div className="flex justify-center mb-6">
                        <div className="w-10 h-10 rounded-md bg-gradient-to-br from-cyan-500 to-sky-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                            <Orbit className="w-5 h-5 text-white" strokeWidth={2} />
                        </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/8 border border-red-500/15 px-4 py-3 rounded-sm font-mono mb-6 text-left">
                        <AlertCircle className="w-4 h-4 flex-shrink-0" />
                        {error}
                    </div>
                    <Link
                        to="/login"
                        className="text-[11px] font-mono text-cyan-400/70 hover:text-cyan-400 transition-colors"
                    >
                        Back to login
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-screen bg-[#050810] items-center justify-center">
            <div
                className="absolute inset-0 pointer-events-none"
                style={{
                    backgroundImage:
                        "radial-gradient(circle, hsl(220 35% 18% / 0.6) 1px, transparent 1px)",
                    backgroundSize: "20px 20px",
                    pointerEvents: "none",
                }}
            />
            <div className="relative z-10 flex flex-col items-center gap-4">
                <div className="w-10 h-10 rounded-md bg-gradient-to-br from-cyan-500 to-sky-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                    <Orbit className="w-5 h-5 text-white" strokeWidth={2} />
                </div>
                <div className="flex items-center gap-3">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-cyan-400 rounded-full animate-spin" />
                    <span className="text-sm font-mono text-white/50">Signing you in...</span>
                </div>
            </div>
        </div>
    );
}
