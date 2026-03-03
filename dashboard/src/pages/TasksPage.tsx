import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { MoreHorizontal, LayoutGrid, List } from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow, parseISO } from "date-fns";
import { ar } from "date-fns/locale";

const STATUS_COLORS: Record<string, string> = {
  todo: "bg-yellow-500/20 text-yellow-400",
  in_progress: "bg-blue-500/20 text-blue-400",
  done: "bg-green-500/20 text-green-400",
  cancelled: "bg-gray-500/20 text-gray-400",
};

const STATUS_LABELS: Record<string, string> = {
  todo: "للتنفيذ", in_progress: "قيد التنفيذ", done: "منتهي", cancelled: "ملغي",
};

const PRIORITY_COLORS = ["", "border-gray-400", "border-blue-400", "border-yellow-400", "border-orange-400", "border-red-500"];

export default function TasksPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: async () => {
      const res = await apiClient(statusFilter === "all" ? "/tasks" : `/tasks?status=${statusFilter}`);
      return res.json();
    },
    staleTime: 30000,
    retry: false,
  });

  const updateTask = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/tasks/update", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); toast.success("تم تحديث المهمة"); },
    onError: (e: any) => toast.error(e.message),
  });

  const deleteTask = useMutation({
    mutationFn: async (title: string) => {
      const res = await apiClient("/tasks/delete", { method: "POST", body: JSON.stringify({ title }) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tasks"] }); toast.success("تم حذف المهمة"); },
    onError: (e: any) => toast.error(e.message),
  });

  const isTextResponse = typeof data?.tasks === "string";
  const allTasks: any[] = Array.isArray(data?.tasks) ? data.tasks : [];

  const columns = ["todo", "in_progress", "done"];

  const TaskCard = ({ task }: { task: any }) => (
    <div className={`bg-card border border-border rounded-lg p-3 space-y-2 border-r-2 ${PRIORITY_COLORS[task.priority] || ""}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium leading-snug flex-1">{task.title}</p>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0">
              <MoreHorizontal className="w-3 h-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {columns.map((s) => s !== task.status && (
              <DropdownMenuItem key={s} onClick={() => updateTask.mutate({ title: task.title, status: s })}>
                → {STATUS_LABELS[s]}
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem className="text-destructive" onClick={() => deleteTask.mutate(task.title)}>
              🗑 حذف
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {task.project && <Badge variant="outline" className="text-xs">{task.project}</Badge>}
        {task.due_date && (
          <span className="text-xs text-muted-foreground">
            {formatDistanceToNow(parseISO(task.due_date), { addSuffix: true, locale: ar })}
          </span>
        )}
        {task.energy_level && <span className="text-xs text-muted-foreground">⚡ {task.energy_level}</span>}
      </div>
    </div>
  );

  return (
    <PageContainer
      title="المهام"
      actions={
        <div className="flex gap-2">
          <Button variant={view === "kanban" ? "default" : "outline"} size="icon" onClick={() => setView("kanban")}>
            <LayoutGrid className="w-4 h-4" />
          </Button>
          <Button variant={view === "list" ? "default" : "outline"} size="icon" onClick={() => setView("list")}>
            <List className="w-4 h-4" />
          </Button>
        </div>
      }
    >
      <Tabs value={statusFilter} onValueChange={setStatusFilter}>
        <TabsList>
          <TabsTrigger value="all">الكل</TabsTrigger>
          <TabsTrigger value="todo">للتنفيذ</TabsTrigger>
          <TabsTrigger value="in_progress">قيد التنفيذ</TabsTrigger>
          <TabsTrigger value="done">منتهي</TabsTrigger>
          <TabsTrigger value="cancelled">ملغي</TabsTrigger>
        </TabsList>
      </Tabs>

      {isLoading && <LoadingSkeleton />}
      {error && <p className="text-destructive text-sm">{(error as any).message}</p>}

      {!isLoading && isTextResponse && (
        <div className="bg-card border border-border rounded-lg p-4">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{data.tasks}</p>
        </div>
      )}

      {!isLoading && !isTextResponse && allTasks.length === 0 && <EmptyState message="لا توجد مهام" />}

      {!isLoading && allTasks.length > 0 && view === "kanban" && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {columns.map((col) => {
            const tasks = allTasks.filter((t) => t.status === col);
            return (
              <div key={col} className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{STATUS_LABELS[col]}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[col]}`}>{tasks.length}</span>
                </div>
                {tasks.map((t, i) => <TaskCard key={i} task={t} />)}
                {tasks.length === 0 && <p className="text-xs text-muted-foreground text-center py-4">لا مهام</p>}
              </div>
            );
          })}
        </div>
      )}

      {!isLoading && allTasks.length > 0 && view === "list" && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-right py-2 px-3">العنوان</th>
                <th className="text-right py-2 px-3">الحالة</th>
                <th className="text-right py-2 px-3">الأولوية</th>
                <th className="text-right py-2 px-3">تاريخ الاستحقاق</th>
                <th className="text-right py-2 px-3">المشروع</th>
              </tr>
            </thead>
            <tbody>
              {allTasks.map((t, i) => (
                <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                  <td className="py-2 px-3 font-medium">{t.title}</td>
                  <td className="py-2 px-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[t.status] || ""}`}>
                      {STATUS_LABELS[t.status] || t.status}
                    </span>
                  </td>
                  <td className="py-2 px-3">{t.priority || "—"}</td>
                  <td className="py-2 px-3 text-muted-foreground">{t.due_date ? formatDistanceToNow(parseISO(t.due_date), { addSuffix: true, locale: ar }) : "—"}</td>
                  <td className="py-2 px-3">{t.project || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageContainer>
  );
}
