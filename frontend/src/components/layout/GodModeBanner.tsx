import { ShieldAlert } from "lucide-react";

interface GodModeBannerProps {
  visible: boolean;
}

export function GodModeBanner({ visible }: GodModeBannerProps) {
  if (!visible) return null;

  return (
    <div className="relative overflow-hidden flex-shrink-0 hazard-scan" style={{ zIndex: 20 }}>
      {/* Hazard diagonal stripe background */}
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage: "repeating-linear-gradient(45deg, hsl(0 84% 60%) 0px, hsl(0 84% 60%) 6px, transparent 6px, transparent 18px)",
        }}
      />

      {/* Solid backing */}
      <div className="absolute inset-0 bg-red-950/70 dark:bg-red-950/80" />

      {/* Content */}
      <div className="relative flex items-center justify-between px-4 py-2 border-b border-red-800/60">
        <div className="flex items-center gap-3">
          {/* Blinking alarm dot */}
          <span
            className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0"
            style={{
              boxShadow: "0 0 8px rgb(239 68 68 / 0.9)",
              animation: "pulse-flash 1.2s ease-in-out infinite",
            }}
          />

          <ShieldAlert className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />

          <span className="text-[11px] font-mono font-bold text-red-300 uppercase tracking-[0.2em]">
            God Mode Active
          </span>

          <span className="hidden sm:inline text-[10px] font-mono text-red-400/60 tracking-wide">
            //
          </span>
          <span className="hidden sm:inline text-[10px] font-mono text-red-400/60">
            destructive actions are armed — proceed with extreme caution
          </span>
        </div>

        {/* Right: ARMED indicator */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[9px] font-mono font-semibold text-red-500/70 uppercase tracking-[0.25em]">
            ARMED
          </span>
          <div className="w-2 h-2 rounded-sm bg-red-600 dark:bg-red-500"
            style={{ animation: "pulse-flash 1.2s ease-in-out infinite 0.6s" }}
          />
        </div>
      </div>
    </div>
  );
}
