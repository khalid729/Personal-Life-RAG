import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import { toast } from "sonner";

const STATUS_COLORS: Record<string, string> = {
  idea: "bg-gray-500/20 text-gray-400",
  planning: "bg-blue-500/20 text-blue-400",
  active: "bg-green-500/20 text-green-400",
  paused: "bg-yellow-500/20 text-yellow-400",
  done: "bg-teal-500/20 text-teal-400",
  cancelled: "bg-red-500/20 text-red-400",
};

const STATUS_LABELS: Record<string, string> = {
  idea: "فكرة", planning: "تخطيط", active: "نشط", paused: "متوقف", done: "منتهي", cancelled: "ملغي",
};

export default function ProjectsPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["projects", statusFilter],
    queryFn: async () => {
      const res = await apiClient(statusFilter === "all" ? "/projects" : `/projects?status=${statusFilter}`);
      return res.json();
    },
    staleTime: 30000,
    retry: false,
  });

  const updateProject = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/projects/update", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); toast.success("تم تحديث المشروع"); },
    onError: (e: any) => toast.error(e.message),
  });

  const deleteProject = useMutation({
    mutationFn: async (name: string) => {
      const res = await apiClient("/projects/delete", { method: "POST", body: JSON.stringify({ name }) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); toast.success("تم حذف المشروع"); },
    onError: (e: any) => toast.error(e.message),
  });

  const focusProject = useMutation({
    mutationFn: async (name: string) => {
      const res = await apiClient("/projects/focus", { method: "POST", body: JSON.stringify({ name }) });
      return res.json();
    },
    onSuccess: () => toast.success("تم تركيز المشروع"),
    onError: (e: any) => toast.error(e.message),
  });

  const isTextResponse = typeof data?.projects === "string";
  const projects: any[] = Array.isArray(data?.projects) ? data.projects : [];

  return (
    <PageContainer title="المشاريع">
      <Tabs value={statusFilter} onValueChange={setStatusFilter}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="all">الكل</TabsTrigger>
          {Object.keys(STATUS_LABELS).map((s) => (
            <TabsTrigger key={s} value={s}>{STATUS_LABELS[s]}</TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading && <LoadingSkeleton />}
      {error && <p className="text-destructive text-sm">{(error as any).message}</p>}

      {!isLoading && isTextResponse && (
        <div className="bg-card border border-border rounded-lg p-4">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{data.projects}</p>
        </div>
      )}

      {!isLoading && !isTextResponse && projects.length === 0 && <EmptyState message="لا توجد مشاريع" />}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p: any, i: number) => (
          <div
            key={i}
            className="bg-card border border-border rounded-lg p-4 space-y-3 hover:border-primary/50 transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <h3 className="font-semibold">{p.name}</h3>
                {p.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{p.description}</p>
                )}
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0">
                    <MoreHorizontal className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onClick={() => focusProject.mutate(p.name)}>🎯 تركيز</DropdownMenuItem>
                  {["active", "paused", "done"].map((s) => s !== p.status && (
                    <DropdownMenuItem key={s} onClick={() => updateProject.mutate({ name: p.name, status: s })}>
                      → {STATUS_LABELS[s]}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuItem className="text-destructive" onClick={() => deleteProject.mutate(p.name)}>
                    🗑 حذف
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[p.status] || ""}`}>
                {STATUS_LABELS[p.status] || p.status}
              </span>
              {p.priority && (
                <Badge variant="outline" className="text-xs">أولوية {p.priority}</Badge>
              )}
            </div>
          </div>
        ))}
      </div>
    </PageContainer>
  );
}
