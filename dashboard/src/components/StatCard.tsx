import React from "react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  color?: string;
  loading?: boolean;
  subtitle?: string;
}

export const StatCard: React.FC<StatCardProps> = ({ title, value, icon, color, loading, subtitle }) => {
  return (
    <div className="stat-card rounded-lg bg-card border border-border p-5 flex items-start gap-4">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: color ? `${color}22` : undefined }}
      >
        <span style={{ color: color || "hsl(var(--primary))" }}>{icon}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-muted-foreground">{title}</p>
        {loading ? (
          <div className="h-7 w-16 bg-muted animate-pulse rounded mt-1" />
        ) : (
          <p className="text-2xl font-bold text-foreground mt-0.5">{value}</p>
        )}
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
      </div>
    </div>
  );
};
