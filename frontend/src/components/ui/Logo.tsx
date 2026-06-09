import { Container, Infinity } from "lucide-react";

export function Logo({ className = "", size = "default" }: { className?: string, size?: "default" | "large" }) {
    const iconSize = size === "large" ? "w-10 h-10" : "w-6 h-6";
    const textSize = size === "large" ? "text-3xl" : "text-xl";

    return (
        <div className={`flex items-center gap-2 ${className}`}>
            <div className="relative flex items-center justify-center">
                <Container className={`${iconSize} text-blue-500`} />
                <Infinity className={`absolute ${size === "large" ? "w-6 h-6" : "w-4 h-4"} text-purple-400 -bottom-1 -right-1 bg-background rounded-full`} />
            </div>
            <h1 className={`${textSize} font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent`}>
                DokOps
            </h1>
        </div>
    );
}
