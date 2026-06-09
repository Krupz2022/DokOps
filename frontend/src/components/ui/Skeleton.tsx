import { cn } from "../../lib/utils";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn("animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800", className)}
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="bg-white dark:bg-card border border-slate-200 dark:border-border rounded-xl p-5 space-y-3">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-8 w-16" />
      <Skeleton className="h-2 w-32" />
    </div>
  );
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-50 dark:border-border">
      <Skeleton className="h-2 w-2 rounded-full" />
      <Skeleton className="h-3 w-48" />
      <Skeleton className="h-3 w-20" />
      <div className="ml-auto">
        <Skeleton className="h-5 w-16 rounded-full" />
      </div>
    </div>
  );
}
