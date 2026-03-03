import React from "react";
import { Skeleton } from "@/components/ui/skeleton";

interface PageContainerProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}

export const PageContainer: React.FC<PageContainerProps> = ({ title, subtitle, actions, children }) => {
  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
};

export const LoadingSkeleton: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div className="space-y-3">
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton key={i} className="h-16 w-full" />
    ))}
  </div>
);

export const EmptyState: React.FC<{ message?: string }> = ({ message = "لا توجد بيانات" }) => (
  <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
    <div className="text-4xl mb-3">📭</div>
    <p className="text-sm">{message}</p>
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div className="flex flex-col items-center justify-center py-16 text-destructive">
    <div className="text-4xl mb-3">⚠️</div>
    <p className="text-sm mb-3">{message}</p>
    {onRetry && (
      <button onClick={onRetry} className="text-xs text-primary underline">
        إعادة المحاولة
      </button>
    )}
  </div>
);
