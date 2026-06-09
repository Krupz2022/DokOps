import { useState } from "react";
import api from "../lib/api";
import { Input } from "../components/ui/Input";
import { AlertCircle, Eye, EyeOff, Orbit } from "lucide-react";
import { cn } from "../lib/utils";
import SSOButtons from "../components/SSOButtons";

export default function Setup() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSetup = async (e: React.FormEvent) => {
        e.preventDefault();
        if (password !== confirmPassword) {
            setError("Passwords do not match");
            return;
        }
        setLoading(true);
        setError("");
        try {
            const response = await api.post("/system/setup", { username, password });
            localStorage.setItem("access_token", response.data.access_token);
            localStorage.setItem("user", JSON.stringify({
                username: response.data.username,
                role: response.data.role,
                is_superuser: response.data.is_superuser,
            }));
            window.location.replace("/dashboard");
        } catch (err: unknown) {
            const e = err as { response?: { status?: number } };
            if (e.response?.status === 403) {
                setError("Setup already complete. Please sign in.");
            } else {
                setError("Failed to create admin account. Try again.");
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex h-screen bg-[#050810] overflow-hidden">
            {/* Dot grid */}
            <div
                className="absolute inset-0"
                style={{
                    backgroundImage: "radial-gradient(circle, hsl(220 35% 18% / 0.6) 1px, transparent 1px)",
                    backgroundSize: "20px 20px",
                }}
            />

            {/* Ambient glow */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[300px] bg-cyan-500/5 rounded-full blur-[80px] pointer-events-none" />

            {/* Left panel — branding */}
            <div className="hidden lg:flex flex-col justify-between w-1/2 border-r border-white/5 p-12 relative z-10">
                <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-md bg-gradient-to-br from-cyan-500 to-sky-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                        <Orbit className="w-4 h-4 text-white" strokeWidth={2} />
                    </div>
                    <span className="text-white font-semibold text-sm tracking-tight">DokOps</span>
                </div>

                <div>
                    <p className="text-[11px] font-mono text-cyan-400/70 uppercase tracking-[0.2em] mb-4">
                        Kubernetes Operations Platform
                    </p>
                    <h2 className="text-4xl font-bold text-white leading-tight mb-4 tracking-tight">
                        Initialize<br />Your<br />Command
                    </h2>
                    <p className="text-sm text-white/40 leading-relaxed max-w-xs">
                        Set up your admin account to take full control of cluster visibility, AI diagnostics, and automated runbooks.
                    </p>

                    <div className="mt-10 flex flex-col gap-3">
                        {[
                            { label: "cluster health", value: "monitored" },
                            { label: "ai diagnostics", value: "active" },
                            { label: "runbook engine", value: "ready" },
                        ].map((item) => (
                            <div key={item.label} className="flex items-center gap-3">
                                <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full dot-pulse" />
                                <span className="text-[11px] font-mono text-white/30 uppercase tracking-wider">{item.label}</span>
                                <div className="flex-1 border-t border-dashed border-white/5" />
                                <span className="text-[11px] font-mono text-emerald-400/70">{item.value}</span>
                            </div>
                        ))}
                    </div>
                </div>

                <p className="text-[10px] font-mono text-white/15">
                    v1.0.0 · Crafted by Krupz
                </p>
            </div>

            {/* Right panel — form */}
            <div className="flex flex-col items-center justify-center flex-1 px-6 relative z-10">
                {/* Mobile logo */}
                <div className="lg:hidden flex items-center gap-2.5 mb-10">
                    <div className="w-8 h-8 rounded-md bg-gradient-to-br from-cyan-500 to-sky-600 flex items-center justify-center">
                        <Orbit className="w-4 h-4 text-white" strokeWidth={2} />
                    </div>
                    <span className="text-white font-semibold text-sm">DokOps</span>
                </div>

                <div className="w-full max-w-sm">
                    <div className="mb-8">
                        <h1 className="text-2xl font-bold text-white tracking-tight mb-1">Initialize platform</h1>
                        <p className="text-sm text-white/35 font-mono">Create the administrator account</p>
                    </div>

                    <form onSubmit={handleSetup} className="space-y-3">
                        <div>
                            <label className="block text-[10px] font-mono text-white/30 uppercase tracking-[0.15em] mb-1.5">
                                Username
                            </label>
                            <Input
                                type="text"
                                placeholder="admin"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                className="bg-white/5 border-white/10 text-white placeholder:text-white/20 focus-visible:ring-cyan-500 focus-visible:border-cyan-500/50 h-10 rounded-sm font-mono text-sm"
                                required
                            />
                        </div>

                        <div>
                            <label className="block text-[10px] font-mono text-white/30 uppercase tracking-[0.15em] mb-1.5">
                                Password
                            </label>
                            <div className="relative">
                                <Input
                                    type={showPassword ? "text" : "password"}
                                    placeholder="••••••••"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="bg-white/5 border-white/10 text-white placeholder:text-white/20 focus-visible:ring-cyan-500 focus-visible:border-cyan-500/50 h-10 rounded-sm pr-10 font-mono text-sm"
                                    required
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/25 hover:text-white/60 transition-colors"
                                >
                                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                </button>
                            </div>
                        </div>

                        <div>
                            <label className="block text-[10px] font-mono text-white/30 uppercase tracking-[0.15em] mb-1.5">
                                Confirm Password
                            </label>
                            <div className="relative">
                                <Input
                                    type={showConfirmPassword ? "text" : "password"}
                                    placeholder="••••••••"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    className="bg-white/5 border-white/10 text-white placeholder:text-white/20 focus-visible:ring-cyan-500 focus-visible:border-cyan-500/50 h-10 rounded-sm pr-10 font-mono text-sm"
                                    required
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/25 hover:text-white/60 transition-colors"
                                >
                                    {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                </button>
                            </div>
                        </div>

                        {error && (
                            <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/8 border border-red-500/15 px-3 py-2.5 rounded-sm font-mono">
                                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                                {error}
                            </div>
                        )}

                        <div className="pt-1">
                            <button
                                type="submit"
                                disabled={loading}
                                className={cn(
                                    "w-full h-10 text-sm font-semibold transition-all duration-150 rounded-sm",
                                    "bg-gradient-to-r from-cyan-500 to-sky-500 text-white",
                                    "hover:from-cyan-400 hover:to-sky-400",
                                    "shadow-lg shadow-cyan-500/20",
                                    "disabled:opacity-50 disabled:cursor-not-allowed",
                                    "flex items-center justify-center gap-2"
                                )}
                            >
                                {loading ? (
                                    <>
                                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                        Initializing...
                                    </>
                                ) : (
                                    "Create Admin Account"
                                )}
                            </button>
                        </div>
                    </form>

                    <SSOButtons />
                </div>
            </div>
        </div>
    );
}
