import { useEffect, useState } from "react";
import api from "../lib/api";
import { cn } from "../lib/utils";


interface SSOProvider {
  name: string;
  label: string;
}

export default function SSOButtons() {
  const [providers, setProviders] = useState<SSOProvider[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<SSOProvider[]>("/auth/sso/providers")
      .then((res) => {
        setProviders(Array.isArray(res.data) ? res.data : []);
      })
      .catch(() => {
        setProviders([]);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  if (loading || providers.length === 0) {
    return null;
  }

  const baseUrl = (
    api.defaults.baseURL ??
    import.meta.env.VITE_API_URL ??
    "http://localhost:8000/api/v1"
  ).replace(/\/$/, "");

  return (
    <div className="mt-5">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex-1 border-t border-white/8" />
        <span className="text-[10px] font-mono text-white/25 uppercase tracking-[0.2em]">
          or
        </span>
        <div className="flex-1 border-t border-white/8" />
      </div>

      <div className="flex flex-col gap-2">
        {providers.map((provider) => (
          <button
            key={provider.name}
            type="button"
            aria-label={`Sign in with ${provider.label}`}
            onClick={() => {
              window.location.href = `${baseUrl}/auth/sso/${provider.name}/login`;
            }}
            className={cn(
              "w-full h-10 text-sm font-semibold transition-all duration-150 rounded-sm",
              "bg-white/5 border border-white/10 text-white/70",
              "hover:bg-white/10 hover:border-white/20 hover:text-white",
              "flex items-center justify-center gap-2",
              "font-mono"
            )}
          >
            Continue with {provider.label}
          </button>
        ))}
      </div>
    </div>
  );
}
