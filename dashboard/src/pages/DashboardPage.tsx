import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, CheckSquare, FolderOpen, DollarSign, Network, Package } from "lucide-react";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { StatCard } from "@/components/StatCard";
import { apiClient } from "@/config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PieChart, Pie, Cell, Tooltip, Legend, BarChart, Bar, XAxis, YAxis, ResponsiveContainer } from "recharts";
import { formatDistanceToNow } from "date-fns";
import { ar } from "date-fns/locale";

const ENTITY_COLORS: Record<string, string> = {
  Person: "#4A90D9", Project: "#E8943A", Task: "#5CB85C", Expense: "#D9534F",
  Debt: "#F0AD4E", Reminder: "#9B59B6", Company: "#3498DB", Item: "#1ABC9C",
  Knowledge: "#2ECC71", Topic: "#95A5A6", Tag: "#BDC3C7", Sprint: "#E74C3C",
  Idea: "#F39C12", FocusSession: "#8E44AD", Place: "#16A085", File: "#607D8B",
};

const fetchJson = async (path: string) => {
  const res = await apiClient(path);
  return res.json();
};

export default function DashboardPage() {
  const { data: reminders, isLoading: rLoading } = useQuery({
    queryKey: ["reminders", "pending"],
    queryFn: () => fetchJson("/reminders?status=pending"),
    staleTime: 30000,
    retry: false,
  });

  const { data: tasksTodo } = useQuery({
    queryKey: ["tasks", "todo"],
    queryFn: () => fetchJson("/tasks?status=todo"),
    staleTime: 30000,
    retry: false,
  });

  const { data: tasksIP } = useQuery({
    queryKey: ["tasks", "in_progress"],
    queryFn: () => fetchJson("/tasks?status=in_progress"),
    staleTime: 30000,
    retry: false,
  });

  const { data: projects } = useQuery({
    queryKey: ["projects", "active"],
    queryFn: () => fetchJson("/projects?status=active"),
    staleTime: 30000,
    retry: false,
  });

  const now = new Date();
  const { data: financial } = useQuery({
    queryKey: ["financial-report", now.getMonth() + 1, now.getFullYear()],
    queryFn: () => fetchJson(`/financial/report?month=${now.getMonth() + 1}&year=${now.getFullYear()}`),
    staleTime: 30000,
    retry: false,
  });

  const { data: graphStats } = useQuery({
    queryKey: ["graph-stats"],
    queryFn: () => fetchJson("/graph/stats"),
    staleTime: 300000,
    retry: false,
  });

  const { data: inventory } = useQuery({
    queryKey: ["inventory"],
    queryFn: () => fetchJson("/inventory"),
    staleTime: 30000,
    retry: false,
  });

  const { data: debts } = useQuery({
    queryKey: ["financial-debts"],
    queryFn: () => fetchJson("/financial/debts"),
    staleTime: 30000,
    retry: false,
  });

  const { data: morningSummary } = useQuery({
    queryKey: ["morning-summary"],
    queryFn: () => fetchJson("/proactive/morning-summary"),
    staleTime: 300000,
    retry: false,
  });

  // Backend returns text strings for these endpoints — count lines as items
  const countTextItems = (text: string | undefined) => {
    if (!text) return 0;
    return (text.match(/^ {2}- /gm) || []).length;
  };
  const reminderCount = typeof reminders?.reminders === "string" ? countTextItems(reminders.reminders) : (Array.isArray(reminders?.reminders) ? reminders.reminders.length : 0);
  const taskCount = (typeof tasksTodo?.tasks === "string" ? countTextItems(tasksTodo.tasks) : (Array.isArray(tasksTodo?.tasks) ? tasksTodo.tasks.length : 0)) +
    (typeof tasksIP?.tasks === "string" ? countTextItems(tasksIP.tasks) : (Array.isArray(tasksIP?.tasks) ? tasksIP.tasks.length : 0));
  const projectCount = typeof projects?.projects === "string" ? countTextItems(projects.projects) : (Array.isArray(projects?.projects) ? projects.projects.length : 0);
  const inventoryCount = typeof inventory?.items === "string" ? countTextItems(inventory.items) : (Array.isArray(inventory?.items) ? inventory.items.length : 0);

  const pieData = Array.isArray(financial?.by_category)
    ? financial.by_category.map((c: any) => ({ name: c.category, value: c.total }))
    : [];

  const barData = graphStats?.by_type
    ? Object.entries(graphStats.by_type).map(([name, value]) => ({ name, value, fill: ENTITY_COLORS[name] || "#4A90D9" }))
    : [];

  return (
    <PageContainer title="لوحة التحكم" subtitle="نظرة عامة على نظام RAG الشخصي">
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard
          title="التذكيرات المعلقة"
          value={rLoading ? "..." : reminderCount}
          icon={<Bell className="w-5 h-5" />}
          color="#9B59B6"
          loading={rLoading}
        />
        <StatCard
          title="المهام النشطة"
          value={taskCount}
          icon={<CheckSquare className="w-5 h-5" />}
          color="#5CB85C"
        />
        <StatCard
          title="المشاريع النشطة"
          value={projectCount}
          icon={<FolderOpen className="w-5 h-5" />}
          color="#E8943A"
        />
        <StatCard
          title="مصاريف الشهر"
          value={financial?.total ? `${financial.total} ر.س` : "—"}
          icon={<DollarSign className="w-5 h-5" />}
          color="#D9534F"
        />
        <StatCard
          title="عقد الرسم البياني"
          value={graphStats?.total_nodes ?? "—"}
          icon={<Network className="w-5 h-5" />}
          color="#4A90D9"
        />
        <StatCard
          title="عناصر المخزون"
          value={inventoryCount}
          icon={<Package className="w-5 h-5" />}
          color="#1ABC9C"
        />
      </div>

      {/* Row 2 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Upcoming reminders */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Bell className="w-4 h-4 text-[#9B59B6]" /> التذكيرات القادمة
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {typeof reminders?.reminders === "string" ? (
              <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">{reminders.reminders}</p>
            ) : reminderCount === 0 ? (
              <EmptyState message="لا توجد تذكيرات معلقة" />
            ) : (
              (reminders?.reminders || []).slice(0, 5).map((r: any, i: number) => (
                <div key={i} className="flex items-start justify-between p-3 rounded-md bg-muted/50">
                  <div>
                    <p className="text-sm font-medium">{r.title}</p>
                    {r.due_date && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {formatDistanceToNow(new Date(r.due_date), { addSuffix: true, locale: ar })}
                      </p>
                    )}
                  </div>
                  <Badge variant="secondary" className="text-xs shrink-0">
                    {r.reminder_type || "تذكير"}
                  </Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Morning summary */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">خطة اليوم ☀️</CardTitle>
          </CardHeader>
          <CardContent>
            {morningSummary?.daily_plan ? (
              <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                {morningSummary.daily_plan}
              </p>
            ) : (
              <EmptyState message="لا توجد خطة صباحية" />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 3: charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">المصاريف حسب الفئة</CardTitle>
          </CardHeader>
          <CardContent>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
                    {pieData.map((_, i) => (
                      <Cell key={i} fill={Object.values(ENTITY_COLORS)[i % 16]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: any) => `${v} ر.س`} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="لا توجد بيانات مالية" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">إحصائيات الرسم البياني</CardTitle>
          </CardHeader>
          <CardContent>
            {barData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData}>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {barData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="لا توجد بيانات" />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Row 4: Debts */}
      {debts && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">ملخص الديون</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center">
                <p className="text-xs text-muted-foreground">عليّ</p>
                <p className="text-xl font-bold text-destructive">{debts.total_i_owe ?? 0} ر.س</p>
              </div>
              <div className="text-center">
                <p className="text-xs text-muted-foreground">لي</p>
                <p className="text-xl font-bold text-[#5CB85C]">{debts.total_owed_to_me ?? 0} ر.س</p>
              </div>
              <div className="text-center">
                <p className="text-xs text-muted-foreground">الصافي</p>
                <p className={`text-xl font-bold ${(debts.net_position ?? 0) >= 0 ? "text-[#4A90D9]" : "text-destructive"}`}>
                  {debts.net_position ?? 0} ر.س
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </PageContainer>
  );
}
