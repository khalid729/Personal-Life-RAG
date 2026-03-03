import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { formatDistanceToNow, parseISO } from "date-fns";
import { ar } from "date-fns/locale";

export default function ProactivePage() {
  const { data: morning, isLoading: ml } = useQuery({
    queryKey: ["morning-summary"],
    queryFn: async () => { const res = await apiClient("/proactive/morning-summary"); return res.json(); },
    staleTime: 300000,
    retry: false,
  });

  const { data: noon, isLoading: nl } = useQuery({
    queryKey: ["noon-checkin"],
    queryFn: async () => { const res = await apiClient("/proactive/noon-checkin"); return res.json(); },
    staleTime: 300000,
    retry: false,
  });

  const { data: evening, isLoading: el } = useQuery({
    queryKey: ["evening-summary"],
    queryFn: async () => { const res = await apiClient("/proactive/evening-summary"); return res.json(); },
    staleTime: 300000,
    retry: false,
  });

  const { data: stalled } = useQuery({
    queryKey: ["stalled-projects"],
    queryFn: async () => { const res = await apiClient("/proactive/stalled-projects?days=14"); return res.json(); },
    staleTime: 60000,
    retry: false,
  });

  const { data: oldDebts } = useQuery({
    queryKey: ["old-debts"],
    queryFn: async () => { const res = await apiClient("/proactive/old-debts?days=30"); return res.json(); },
    staleTime: 60000,
    retry: false,
  });

  return (
    <PageContainer title="المساعد التلقائي">
      <Tabs defaultValue="morning">
        <TabsList>
          <TabsTrigger value="morning">☀️ الصباح</TabsTrigger>
          <TabsTrigger value="noon">🌤 الظهر</TabsTrigger>
          <TabsTrigger value="evening">🌙 المساء</TabsTrigger>
          <TabsTrigger value="alerts">⚠️ تنبيهات</TabsTrigger>
        </TabsList>

        <TabsContent value="morning" className="space-y-4">
          {ml && <LoadingSkeleton rows={3} />}
          {morning?.daily_plan && (
            <Card>
              <CardHeader><CardTitle className="text-sm">خطة اليوم</CardTitle></CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{morning.daily_plan}</p>
              </CardContent>
            </Card>
          )}
          {morning?.spending_alerts && (
            <Card className="border-yellow-500/30 bg-yellow-500/5">
              <CardContent className="p-4">
                <p className="text-sm">{morning.spending_alerts}</p>
              </CardContent>
            </Card>
          )}
          {morning?.timeblock_suggestion?.blocks && (
            <Card>
              <CardHeader><CardTitle className="text-sm">جدول الوقت المقترح</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {morning.timeblock_suggestion.blocks.map((block: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 p-2 rounded-md bg-muted/50">
                      <span className="text-xs font-mono text-muted-foreground">{block.time || block.start}</span>
                      <span className="text-sm">{block.task || block.title}</span>
                      {block.energy && <Badge variant="outline" className="text-xs">{block.energy}</Badge>}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {!ml && !morning && <EmptyState message="لا يوجد ملخص صباحي" />}
        </TabsContent>

        <TabsContent value="noon" className="space-y-3">
          {nl && <LoadingSkeleton rows={3} />}
          {noon?.overdue_reminders?.map((r: any, i: number) => (
            <div key={i} className="bg-card border border-destructive/30 rounded-lg p-4 flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-sm">{r.title}</p>
                <p className="text-xs text-destructive mt-1">{r.due_date}</p>
                {r.description && <p className="text-xs text-muted-foreground mt-1">{r.description}</p>}
              </div>
              <Badge className="bg-destructive/20 text-destructive text-xs shrink-0">متأخر</Badge>
            </div>
          ))}
          {!nl && !noon?.overdue_reminders?.length && <EmptyState message="لا توجد تذكيرات متأخرة" />}
        </TabsContent>

        <TabsContent value="evening" className="space-y-4">
          {el && <LoadingSkeleton rows={3} />}
          {evening?.completed_today && (
            <Card>
              <CardHeader><CardTitle className="text-sm">المنجزات اليوم ✅</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {(Array.isArray(evening.completed_today) ? evening.completed_today : [evening.completed_today]).map((item: any, i: number) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <span className="text-green-400">✓</span>
                      <span>{typeof item === "string" ? item : item.title}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {evening?.tomorrow_reminders && (
            <Card>
              <CardHeader><CardTitle className="text-sm">تذكيرات الغد</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {evening.tomorrow_reminders.map((r: any, i: number) => (
                    <div key={i} className="p-2 rounded-md bg-muted/50 text-sm">{r.title || r}</div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {!el && !evening && <EmptyState message="لا يوجد ملخص مسائي" />}
        </TabsContent>

        <TabsContent value="alerts" className="space-y-4">
          {stalled?.stalled_projects?.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">مشاريع متوقفة ⏸</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {stalled.stalled_projects.map((p: any, i: number) => (
                    <div key={i} className="flex items-center justify-between p-2 rounded-md bg-muted/50 text-sm">
                      <span>{p.name}</span>
                      <Badge variant="outline" className="text-xs">{p.status}</Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {oldDebts?.old_debts?.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">ديون قديمة 💸</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {oldDebts.old_debts.map((d: any, i: number) => (
                    <div key={i} className="flex items-center justify-between p-2 rounded-md bg-muted/50 text-sm">
                      <span>{d.person}</span>
                      <span className="font-medium">{d.amount} ر.س</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
          {!stalled?.stalled_projects?.length && !oldDebts?.old_debts?.length && <EmptyState message="لا توجد تنبيهات" />}
        </TabsContent>
      </Tabs>
    </PageContainer>
  );
}
