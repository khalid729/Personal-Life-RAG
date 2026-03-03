import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";

export default function ProductivityPage() {
  const [sprintDialog, setSprintDialog] = useState(false);
  const [focusDialog, setFocusDialog] = useState(false);
  const [sprintForm, setSprintForm] = useState({ name: "", project: "", start_date: "", end_date: "", goal: "" });
  const [focusForm, setFocusForm] = useState({ task: "", duration_minutes: 25 });
  const [tbDate, setTbDate] = useState(new Date().toISOString().slice(0, 10));
  const [tbEnergy, setTbEnergy] = useState("normal");
  const [tbResult, setTbResult] = useState<any>(null);
  const qc = useQueryClient();

  const { data: sprints, isLoading: sl } = useQuery({
    queryKey: ["sprints"],
    queryFn: async () => { const res = await apiClient("/productivity/sprints/"); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const { data: focusStats } = useQuery({
    queryKey: ["focus-stats"],
    queryFn: async () => { const res = await apiClient("/productivity/focus/stats"); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const createSprint = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/productivity/sprints/", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["sprints"] }); toast.success("تم إنشاء السبرينت"); setSprintDialog(false); },
    onError: (e: any) => toast.error(e.message),
  });

  const startFocus = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/productivity/focus/start", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { toast.success("بدأت جلسة التركيز"); setFocusDialog(false); },
    onError: (e: any) => toast.error(e.message),
  });

  const completeFocus = useMutation({
    mutationFn: async () => {
      const res = await apiClient("/productivity/focus/complete", { method: "POST", body: JSON.stringify({ completed: true }) });
      return res.json();
    },
    onSuccess: () => { toast.success("انتهت جلسة التركيز"); qc.invalidateQueries({ queryKey: ["focus-stats"] }); },
    onError: (e: any) => toast.error(e.message),
  });

  const suggestTimeblock = useMutation({
    mutationFn: async () => {
      const res = await apiClient("/productivity/timeblock/suggest", {
        method: "POST",
        body: JSON.stringify({ date: tbDate, energy_override: tbEnergy }),
      });
      return res.json();
    },
    onSuccess: (d) => setTbResult(d),
    onError: (e: any) => toast.error(e.message),
  });

  const applyTimeblock = useMutation({
    mutationFn: async () => {
      const res = await apiClient("/productivity/timeblock/apply", {
        method: "POST",
        body: JSON.stringify({ blocks: tbResult?.blocks }),
      });
      return res.json();
    },
    onSuccess: () => toast.success("تم تطبيق الجدول"),
    onError: (e: any) => toast.error(e.message),
  });

  const sprintList: any[] = Array.isArray(sprints?.sprints) ? sprints.sprints : [];

  const focusByTask = focusStats?.by_task
    ? Object.entries(focusStats.by_task).map(([name, value]) => ({ name, value }))
    : [];

  return (
    <PageContainer
      title="الإنتاجية"
      actions={
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setSprintDialog(true)}>+ سبرينت</Button>
          <Button size="sm" variant="outline" onClick={() => setFocusDialog(true)}>⏱ تركيز</Button>
        </div>
      }
    >
      <Tabs defaultValue="sprints">
        <TabsList>
          <TabsTrigger value="sprints">السبرينتات</TabsTrigger>
          <TabsTrigger value="focus">جلسات التركيز</TabsTrigger>
          <TabsTrigger value="timeblock">جدولة الوقت</TabsTrigger>
        </TabsList>

        <TabsContent value="sprints" className="space-y-3">
          {sl && <LoadingSkeleton />}
          {!sl && sprintList.length === 0 && <EmptyState message="لا توجد سبرينتات" />}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {sprintList.map((s: any, i: number) => (
              <Card key={i}>
                <CardContent className="p-4 space-y-2">
                  <div className="flex justify-between items-start">
                    <h3 className="font-semibold text-sm">{s.name}</h3>
                    <Badge variant="outline" className="text-xs">{s.status}</Badge>
                  </div>
                  {s.goal && <p className="text-xs text-muted-foreground">{s.goal}</p>}
                  {s.project && <Badge className="text-xs">{s.project}</Badge>}
                  <div className="text-xs text-muted-foreground">
                    {s.start_date} → {s.end_date}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="focus" className="space-y-4">
          <Button variant="outline" size="sm" onClick={() => completeFocus.mutate()}>إنهاء جلسة التركيز الحالية</Button>
          {focusStats && (
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "اليوم", sessions: focusStats.today_sessions, minutes: focusStats.today_minutes },
                { label: "هذا الأسبوع", sessions: focusStats.week_sessions, minutes: focusStats.week_minutes },
                { label: "الإجمالي", sessions: focusStats.total_sessions, minutes: focusStats.total_minutes },
              ].map((stat) => (
                <Card key={stat.label} className="text-center p-4">
                  <p className="text-xs text-muted-foreground">{stat.label}</p>
                  <p className="text-xl font-bold">{stat.sessions || 0}</p>
                  <p className="text-xs text-muted-foreground">{stat.minutes || 0} دقيقة</p>
                </Card>
              ))}
            </div>
          )}
          {focusByTask.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">الوقت حسب المهمة</CardTitle></CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={focusByTask}>
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="timeblock" className="space-y-4">
          <div className="flex gap-2 flex-wrap items-end">
            <div>
              <Label className="text-xs">التاريخ</Label>
              <Input type="date" value={tbDate} onChange={e => setTbDate(e.target.value)} className="w-40" />
            </div>
            <div>
              <Label className="text-xs">مستوى الطاقة</Label>
              <Select value={tbEnergy} onValueChange={setTbEnergy}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="normal">عادي</SelectItem>
                  <SelectItem value="tired">متعب</SelectItem>
                  <SelectItem value="energized">نشط</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={() => suggestTimeblock.mutate()} disabled={suggestTimeblock.isPending}>
              {suggestTimeblock.isPending ? "جاري..." : "اقتراح جدول"}
            </Button>
          </div>

          {tbResult?.blocks && (
            <>
              <div className="space-y-2">
                {tbResult.blocks.map((block: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 p-3 rounded-md bg-muted/50">
                    <span className="text-xs font-mono text-muted-foreground w-16 shrink-0">{block.time || block.start}</span>
                    <span className="text-sm flex-1">{block.task || block.title}</span>
                    {block.energy && <Badge variant="outline" className="text-xs">{block.energy}</Badge>}
                  </div>
                ))}
              </div>
              <Button variant="outline" size="sm" onClick={() => applyTimeblock.mutate()}>تطبيق الجدول</Button>
            </>
          )}
        </TabsContent>
      </Tabs>

      {/* Sprint Dialog */}
      <Dialog open={sprintDialog} onOpenChange={setSprintDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>إنشاء سبرينت جديد</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>الاسم *</Label><Input value={sprintForm.name} onChange={e => setSprintForm(p => ({ ...p, name: e.target.value }))} /></div>
            <div><Label>المشروع</Label><Input value={sprintForm.project} onChange={e => setSprintForm(p => ({ ...p, project: e.target.value }))} /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>تاريخ البدء</Label><Input type="date" value={sprintForm.start_date} onChange={e => setSprintForm(p => ({ ...p, start_date: e.target.value }))} /></div>
              <div><Label>تاريخ الانتهاء</Label><Input type="date" value={sprintForm.end_date} onChange={e => setSprintForm(p => ({ ...p, end_date: e.target.value }))} /></div>
            </div>
            <div><Label>الهدف</Label><Input value={sprintForm.goal} onChange={e => setSprintForm(p => ({ ...p, goal: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button onClick={() => createSprint.mutate(sprintForm)} disabled={!sprintForm.name}>إنشاء</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Focus Dialog */}
      <Dialog open={focusDialog} onOpenChange={setFocusDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>بدء جلسة تركيز</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>المهمة (اختياري)</Label><Input value={focusForm.task} onChange={e => setFocusForm(p => ({ ...p, task: e.target.value }))} /></div>
            <div><Label>المدة (دقيقة)</Label><Input type="number" value={focusForm.duration_minutes} onChange={e => setFocusForm(p => ({ ...p, duration_minutes: Number(e.target.value) }))} /></div>
          </div>
          <DialogFooter>
            <Button onClick={() => startFocus.mutate(focusForm)}>بدء</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
