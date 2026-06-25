import { useEffect, useState } from "react";
import { Heart, Github, ExternalLink } from "lucide-react";

function LiveClock() {
  const [time, setTime] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hh = String(time.getUTCHours()).padStart(2, "0");
  const mm = String(time.getUTCMinutes()).padStart(2, "0");
  const ss = String(time.getUTCSeconds()).padStart(2, "0");

  return (
    <span className="font-mono text-[11px] text-muted-foreground/60 tabular-nums tracking-widest">
      {hh}:{mm}:{ss} <span className="opacity-50">UTC</span>
    </span>
  );
}

export function Footer() {
  return (
    <footer className="flex-shrink-0 border-t border-border h-10 flex items-center bg-card/50 backdrop-blur-sm dark:bg-[hsl(220_44%_4%_/_0.6)]">
      <div className="w-full px-5 flex items-center justify-between gap-4">

        {/* Left: branding */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground min-w-0">
          <span className="font-semibold text-foreground/80 tracking-tight hidden sm:inline">DokOps Platform</span>
          <span className="hidden sm:inline text-muted-foreground/30">·</span>
          <div className="flex items-center gap-1">
            <span className="hidden md:inline">Crafted with</span>
            <Heart className="w-3 h-3 text-red-500 fill-red-500" style={{ animation: "pulse-dot 2s ease-in-out infinite" }} />
            <span className="hidden md:inline">by <span className="font-medium text-foreground/70">Krupz</span></span>
          </div>
        </div>

        {/* Center: live clock */}
        <div className="hidden md:flex items-center gap-2">
          {/* System online indicator */}
          <span
            className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0"
            style={{
              boxShadow: "0 0 5px rgb(52 211 153 / 0.7)",
              animation: "pulse-dot 2s ease-in-out infinite",
            }}
          />
          <span className="font-mono text-[10px] text-muted-foreground/40 uppercase tracking-[0.18em] mr-2">sys:online</span>
          <LiveClock />
        </div>

        {/* Right: nav + version */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground flex-shrink-0">
          <nav className="hidden sm:flex items-center gap-4">
            <a href="/info" className="hover:text-primary transition-colors">About</a>
            <a href="/docs" className="flex items-center gap-1 hover:text-primary transition-colors group">
              Docs
              <ExternalLink className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100 transition-opacity" />
            </a>
            <a href="https://github.com/Krupz2022/dokops" target="_blank" rel="noreferrer" className="hover:text-foreground transition-colors">
              <Github className="w-3.5 h-3.5" />
            </a>
          </nav>

          <div className="h-3 w-px bg-border hidden sm:block" />

          {/* Version pill — terminal style */}
          <div className="flex items-center gap-1.5 font-mono text-[10px] bg-secondary/60 border border-border/60 px-2 py-0.5 rounded-sm">
            <span
              className="w-1.5 h-1.5 rounded-full bg-emerald-500"
              style={{ boxShadow: "0 0 4px rgb(52 211 153 / 0.7)" }}
            />
            <span className="text-muted-foreground/70">v1.2</span>
          </div>
        </div>

      </div>
    </footer>
  );
}
