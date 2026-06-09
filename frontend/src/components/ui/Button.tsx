import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", loading, children, disabled, ...props }, ref) => {
    const variants: Record<string, string> = {
      default:
        "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm " +
        "dark:shadow-[0_0_16px_hsl(191_89%_55%_/_0.3),0_2px_8px_hsl(0_0%_0%_/_0.4)] " +
        "dark:hover:shadow-[0_0_24px_hsl(191_89%_55%_/_0.45),0_4px_12px_hsl(0_0%_0%_/_0.5)]",
      destructive:
        "bg-red-600 text-white hover:bg-red-700 shadow-sm " +
        "dark:shadow-[0_0_14px_hsl(0_70%_50%_/_0.3)]",
      outline:
        "border border-border bg-transparent hover:bg-secondary text-foreground " +
        "dark:glass dark:hover:border-primary/30 dark:hover:shadow-[0_0_12px_hsl(191_89%_55%_/_0.1)]",
      secondary:
        "bg-secondary text-secondary-foreground hover:bg-secondary/80",
      ghost:
        "hover:bg-secondary text-foreground",
      link:
        "text-primary underline-offset-4 hover:underline",
    };

    const sizes: Record<string, string> = {
      default: "h-9 px-4 py-2 text-sm",
      sm:      "h-7 px-3 text-xs rounded-md",
      lg:      "h-10 px-5 text-sm rounded-md",
      icon:    "h-9 w-9",
    };

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "disabled:pointer-events-none disabled:opacity-50",
          variants[variant],
          sizes[size],
          className
        )}
        {...props}
      >
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button };
