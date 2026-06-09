import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { Input } from "../components/ui/Input";
import { SkeletonRow } from "../components/ui/Skeleton";
import { Trash2, UserPlus, Users, ShieldCheck, Activity, Shield, Loader2 } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { useConfirm } from "../context/ConfirmContext";
import { cn } from "../lib/utils";

export default function Admin() {
    const navigate = useNavigate();
    const { toast } = useToast();
    const { confirm } = useConfirm();
    const [users, setUsers] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [newUser, setNewUser] = useState({ username: "", password: "", is_superuser: false });
    const [signupEnabled, setSignupEnabled] = useState(false);
    const [signupDefaultRole, setSignupDefaultRole] = useState<"user" | "admin">("user");
    const [settingsSaved, setSettingsSaved] = useState(false);
    const [roleUpdating, setRoleUpdating] = useState<number | null>(null);

    useEffect(() => { fetchUsers(); }, []);

    useEffect(() => {
        api.get("/system/status")
            .then(res => {
                setSignupEnabled(res.data.signup_enabled);
                setSignupDefaultRole(res.data.signup_default_role);
            })
            .catch(() => {});
    }, []);

    const fetchUsers = async () => {
        try {
            const res = await api.get("/users/");
            setUsers(res.data);
        } catch {
            navigate("/dashboard");
        } finally {
            setLoading(false);
        }
    };

    const handleCreateUser = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.post("/users/", {
                username: newUser.username,
                hashed_password: newUser.password,
                is_superuser: newUser.is_superuser,
                role: newUser.is_superuser ? "admin" : "user",
            });
            setShowModal(false);
            setNewUser({ username: "", password: "", is_superuser: false });
            fetchUsers();
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to create user", "error");
        }
    };

    const saveSignupSettings = async (enabled: boolean, role: "user" | "admin") => {
        try {
            await api.put("/system/settings", { signup_enabled: enabled, signup_default_role: role });
            setSettingsSaved(true);
            setTimeout(() => setSettingsSaved(false), 2000);
        } catch { /* silent */ }
    };

    const handleToggleSignup = () => {
        const next = !signupEnabled;
        setSignupEnabled(next);
        saveSignupSettings(next, signupDefaultRole);
    };

    const handleRoleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const r = e.target.value as "user" | "admin";
        setSignupDefaultRole(r);
        saveSignupSettings(signupEnabled, r);
    };

    const handleRoleUpdate = async (userId: number, role: string) => {
        setRoleUpdating(userId);
        try {
            await api.patch(`/users/${userId}/role`, { role });
            setUsers(prev => prev.map(u => u.id === userId
                ? { ...u, role, is_superuser: role === "admin" }
                : u
            ));
            toast(`Role updated to ${role}`, "success");
        } catch (err: any) {
            toast(err.response?.data?.detail || "Failed to update role", "error");
        } finally {
            setRoleUpdating(null);
        }
    };

    const handleDeleteUser = async (userId: number) => {
        const ok = await confirm({
            title: "Delete User",
            description: "This user will be permanently removed and cannot be recovered.",
            variant: "danger",
            confirmLabel: "Delete User",
        });
        if (!ok) return;
        try {
            await api.delete(`/users/${userId}`);
            fetchUsers();
        } catch {
            toast("Failed to delete user", "error");
        }
    };

    const totalAdmins = users.filter(u => u.is_superuser).length;
    const totalActive = users.filter(u => u.is_active).length;

    const pageHeader = (
        <div className="flex-shrink-0 px-6 py-4 flex items-center justify-between border-b border-border/60">
            <div>
                <h1 className="text-base font-semibold text-foreground tracking-tight">Admin Panel</h1>
                <p className="text-xs text-muted-foreground font-mono mt-0.5">Manage users and permissions</p>
            </div>
            <Button onClick={() => setShowModal(true)} size="sm" className="h-8 px-3 text-xs gap-1.5">
                <UserPlus className="w-3.5 h-3.5" />
                Create User
            </Button>
        </div>
    );

    if (loading) {
        return (
            <div className="flex flex-col h-full">
                {pageHeader}
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="bg-card border border-border overflow-hidden">
                        {[...Array(3)].map((_, i) => <SkeletonRow key={i} />)}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full">
            {pageHeader}
            <div className="flex-1 overflow-y-auto p-6">
                <div className="space-y-5">

                    {/* Stat row */}
                    <div className="grid grid-cols-3 gap-3 fade-up fade-up-1">
                        {[
                            { label: "Total Users",  value: users.length,  icon: Users,        accent: "stat-card-cyan"  },
                            { label: "Admins",        value: totalAdmins,   icon: ShieldCheck,  accent: "stat-card-amber" },
                            { label: "Active",        value: totalActive,   icon: Activity,     accent: "stat-card-green" },
                        ].map(({ label, value, icon: Icon, accent }) => (
                            <div key={label} className={cn("bg-card border border-border stat-card px-5 py-4", accent)}>
                                <div className="flex items-center justify-between mb-3 pl-3">
                                    <p className="text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.18em]">
                                        {label}
                                    </p>
                                    <div className="w-6 h-6 rounded-md flex items-center justify-center bg-secondary/80 border border-border/60">
                                        <Icon className="w-3 h-3 text-muted-foreground/70" />
                                    </div>
                                </div>
                                <p className="text-3xl font-bold text-foreground pl-3">{value}</p>
                            </div>
                        ))}
                    </div>

                    {/* Users table */}
                    <div className="bg-card border border-border overflow-hidden fade-up fade-up-2">
                        <div className="flex items-center gap-2.5 px-5 py-3 border-b border-border">
                            <Shield className="w-3.5 h-3.5 text-muted-foreground/50" />
                            <h2 className="text-xs font-mono font-semibold text-muted-foreground/70 uppercase tracking-[0.15em]">
                                User Roster
                            </h2>
                            <span className="ml-auto tag tag-cyan">{users.length} users</span>
                        </div>
                        <table className="w-full text-left">
                            <thead>
                                <tr className="border-b border-border bg-secondary/20">
                                    {["ID", "User", "Role", "Status", "Actions"].map((h, i) => (
                                        <th key={h} className={cn(
                                            "h-9 px-5 align-middle text-[9px] font-mono font-semibold text-muted-foreground/50 uppercase tracking-[0.18em]",
                                            i === 4 && "text-right"
                                        )}>
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {users.length === 0 && (
                                    <tr>
                                        <td colSpan={5} className="py-16 text-center text-xs font-mono text-muted-foreground/40">
                                            No users found.
                                        </td>
                                    </tr>
                                )}
                                {users.map((user) => (
                                    <tr key={user.id} className="border-b border-border last:border-0 transition-colors hover:bg-secondary/20">
                                        <td className="px-5 py-3 font-mono text-[11px] text-muted-foreground/50">
                                            #{user.id}
                                        </td>
                                        <td className="px-5 py-3">
                                            <div className="flex items-center gap-2.5">
                                                <div className="relative flex-shrink-0">
                                                    <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-gradient-to-br from-cyan-400 to-sky-600 shadow-sm shadow-cyan-500/30">
                                                        <span className="text-white text-[10px] font-bold">
                                                            {user.username.slice(0, 2).toUpperCase()}
                                                        </span>
                                                    </div>
                                                    {user.is_active && (
                                                        <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-emerald-400 rounded-full border-[1.5px] border-card shadow-[0_0_5px_#4ade8080]" />
                                                    )}
                                                </div>
                                                <span className="text-sm font-medium text-foreground">{user.username}</span>
                                            </div>
                                        </td>
                                        <td className="px-5 py-3">
                                            {roleUpdating === user.id ? (
                                                <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground/50" />
                                            ) : (
                                                <select
                                                    value={user.role ?? (user.is_superuser ? "admin" : "user")}
                                                    onChange={e => handleRoleUpdate(user.id, e.target.value)}
                                                    className={cn(
                                                        "text-[10px] font-mono font-semibold border rounded-sm px-2 py-0.5 outline-none cursor-pointer",
                                                        "bg-transparent focus:ring-1 focus:ring-primary/20 focus:border-primary/40",
                                                        user.is_superuser
                                                            ? "text-primary border-primary/20 bg-primary/8"
                                                            : "text-muted-foreground border-border/60 bg-secondary/60"
                                                    )}
                                                >
                                                    <option value="user">User</option>
                                                    <option value="admin">Admin</option>
                                                </select>
                                            )}
                                        </td>
                                        <td className="px-5 py-3">
                                            <span className={cn(
                                                "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm text-[10px] font-mono font-semibold border",
                                                user.is_active
                                                    ? "bg-emerald-500/8 text-emerald-600 dark:text-emerald-400 border-emerald-500/20"
                                                    : "bg-red-500/8 text-red-600 dark:text-red-400 border-red-500/20"
                                            )}>
                                                <span className={cn(
                                                    "w-1 h-1 rounded-full",
                                                    user.is_active ? "bg-emerald-500" : "bg-red-500"
                                                )} />
                                                {user.is_active ? "Active" : "Inactive"}
                                            </span>
                                        </td>
                                        <td className="px-5 py-3 text-right">
                                            <button
                                                onClick={() => handleDeleteUser(user.id)}
                                                title="Delete User"
                                                className="h-7 w-7 inline-flex items-center justify-center rounded-lg text-muted-foreground/40 hover:text-red-500 hover:bg-red-500/10 transition-colors"
                                            >
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {/* Signup settings */}
                    <div className="bg-card border border-border overflow-hidden fade-up fade-up-3">
                        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
                            <div>
                                <h2 className="text-xs font-mono font-semibold text-muted-foreground/70 uppercase tracking-[0.15em]">
                                    Signup Settings
                                </h2>
                                <p className="text-[11px] text-muted-foreground/50 font-mono mt-0.5">
                                    Control whether users can self-register
                                </p>
                            </div>
                            {settingsSaved && (
                                <span className="text-[10px] font-mono text-emerald-500 flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_5px_rgb(52_211_153_/_0.7)]" />
                                    saved
                                </span>
                            )}
                        </div>

                        <div className="px-5 py-4 space-y-0 divide-y divide-border/60">
                            <div className="flex items-center justify-between py-3">
                                <span className="text-sm text-foreground/80 font-medium">Allow public signups</span>
                                <button
                                    onClick={handleToggleSignup}
                                    className={cn(
                                        "relative w-10 h-5 rounded-full border transition-all duration-300",
                                        signupEnabled
                                            ? "bg-primary/20 border-primary/40 dark:shadow-[0_0_8px_hsl(191_89%_55%_/_0.3)]"
                                            : "bg-secondary border-border"
                                    )}
                                    aria-label="Toggle signups"
                                >
                                    <span className={cn(
                                        "absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full transition-all duration-300",
                                        signupEnabled
                                            ? "left-[calc(100%-1.125rem)] bg-primary shadow-[0_0_6px_hsl(191_89%_55%_/_0.6)]"
                                            : "left-0.5 bg-muted-foreground/40"
                                    )} />
                                </button>
                            </div>

                            {signupEnabled && (
                                <div className="flex items-center justify-between py-3">
                                    <span className="text-sm text-foreground/80 font-medium">Default role for new signups</span>
                                    <select
                                        value={signupDefaultRole}
                                        onChange={handleRoleChange}
                                        className={cn(
                                            "text-xs border border-border bg-background text-foreground rounded-lg px-3 py-1.5 font-mono",
                                            "outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
                                        )}
                                    >
                                        <option value="user">User</option>
                                        <option value="admin">Admin</option>
                                    </select>
                                </div>
                            )}
                        </div>
                    </div>

                </div>
            </div>

            {/* Create User Modal */}
            <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="Create New User" className="max-w-sm">
                <form onSubmit={handleCreateUser} className="space-y-4 pt-1">
                    <div className="space-y-1.5">
                        <label className="text-xs font-mono font-medium text-muted-foreground">Username</label>
                        <Input
                            value={newUser.username}
                            onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                            required
                        />
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-xs font-mono font-medium text-muted-foreground">Password</label>
                        <Input
                            type="password"
                            value={newUser.password}
                            onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                            required
                        />
                    </div>
                    <div className="flex items-center gap-2.5 py-2">
                        <button
                            type="button"
                            onClick={() => setNewUser(u => ({ ...u, is_superuser: !u.is_superuser }))}
                            className={cn(
                                "relative w-10 h-5 rounded-full border transition-all duration-300 flex-shrink-0",
                                newUser.is_superuser
                                    ? "bg-primary/20 border-primary/40 dark:shadow-[0_0_8px_hsl(191_89%_55%_/_0.3)]"
                                    : "bg-secondary border-border"
                            )}
                        >
                            <span className={cn(
                                "absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full transition-all duration-300",
                                newUser.is_superuser
                                    ? "left-[calc(100%-1.125rem)] bg-primary shadow-[0_0_6px_hsl(191_89%_55%_/_0.6)]"
                                    : "left-0.5 bg-muted-foreground/40"
                            )} />
                        </button>
                        <label className="text-sm font-medium text-foreground/80 cursor-pointer select-none"
                            onClick={() => setNewUser(u => ({ ...u, is_superuser: !u.is_superuser }))}>
                            Grant Admin Privileges
                        </label>
                    </div>
                    <div className="flex justify-end gap-3 pt-2">
                        <button
                            type="button"
                            onClick={() => setShowModal(false)}
                            className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
                        >
                            Cancel
                        </button>
                        <Button type="submit" size="sm" className="h-8 px-4">
                            Create User
                        </Button>
                    </div>
                </form>
            </Modal>
        </div>
    );
}
