import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";

const COLORS = ["#4A90D9","#E8943A","#5CB85C","#D9534F","#F0AD4E","#9B59B6","#3498DB","#1ABC9C"];

export default function FinancialPage() {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [paymentDialog, setPaymentDialog] = useState(false);
  const [payForm, setPayForm] = useState({ person: "", amount: "", direction: "i_owe" });
  const qc = useQueryClient();

  const { data: report, isLoading: rLoading } = useQuery({
    queryKey: ["financial-report", month, year],
    queryFn: async () => { const res = await apiClient(`/financial/report?month=${month}&year=${year}`); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const { data: debts, isLoading: dLoading } = useQuery({
    queryKey: ["financial-debts"],
    queryFn: async () => { const res = await apiClient("/financial/debts"); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const { data: alerts } = useQuery({
    queryKey: ["financial-alerts"],
    queryFn: async () => { const res = await apiClient("/financial/alerts"); return res.json(); },
    staleTime: 60000,
    retry: false,
  });

  const recordPayment = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/financial/debts/payment", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["financial-debts"] }); toast.success("تم تسجيل الدفعة"); setPaymentDialog(false); },
    onError: (e: any) => toast.error(e.message),
  });

  const pieData = Array.isArray(report?.by_category)
    ? report.by_category.map((c: any) => ({ name: c.category, value: c.total }))
    : [];

  const debtList = Array.isArray(debts?.debts) ? debts.debts : [];
  const netPositive = (debts?.net_position || 0) >= 0;

  return (
    <PageContainer title="المالية">
      <Tabs defaultValue="expenses">
        <TabsList>
          <TabsTrigger value="expenses">المصاريف</TabsTrigger>
          <TabsTrigger value="debts">الديون</TabsTrigger>
          <TabsTrigger value="alerts">التنبيهات</TabsTrigger>
        </TabsList>

        <TabsContent value="expenses" className="space-y-4">
          <div className="flex gap-2 items-center flex-wrap">
            <Select value={String(month)} onValueChange={(v) => setMonth(Number(v))}>
              <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Array.from({ length: 12 }, (_, i) => (
                  <SelectItem key={i+1} value={String(i+1)}>شهر {i+1}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
              <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
              <SelectContent>
                {[2023, 2024, 2025, 2026].map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {rLoading && <LoadingSkeleton rows={3} />}

          {report && (
            <>
              <div className="text-3xl font-bold text-foreground">{report.total || 0} ر.س</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">حسب الفئة</CardTitle></CardHeader>
                  <CardContent>
                    {pieData.length > 0 ? (
                      <ResponsiveContainer width="100%" height={220}>
                        <PieChart>
                          <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={80}>
                            {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                          </Pie>
                          <Tooltip formatter={(v: any) => `${v} ر.س`} />
                          <Legend />
                        </PieChart>
                      </ResponsiveContainer>
                    ) : <EmptyState />}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">تفاصيل الفئات</CardTitle></CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {pieData.map((item, i) => (
                        <div key={i} className="flex justify-between text-sm">
                          <span className="text-muted-foreground">{item.name}</span>
                          <span className="font-medium">{item.value as number} ر.س</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="debts" className="space-y-4">
          {dLoading && <LoadingSkeleton rows={3} />}
          {debts && (
            <>
              <div className="grid grid-cols-3 gap-4">
                <Card className="text-center p-4">
                  <p className="text-xs text-muted-foreground">عليّ</p>
                  <p className="text-2xl font-bold text-destructive">{debts.total_i_owe || 0} ر.س</p>
                </Card>
                <Card className="text-center p-4">
                  <p className="text-xs text-muted-foreground">لي</p>
                  <p className="text-2xl font-bold" style={{ color: "#5CB85C" }}>{debts.total_owed_to_me || 0} ر.س</p>
                </Card>
                <Card className="text-center p-4">
                  <p className="text-xs text-muted-foreground">الصافي</p>
                  <p className={`text-2xl font-bold ${netPositive ? "text-primary" : "text-destructive"}`}>
                    {debts.net_position || 0} ر.س
                  </p>
                </Card>
              </div>
              <Button onClick={() => setPaymentDialog(true)} variant="outline" size="sm">+ تسجيل دفعة</Button>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th className="text-right py-2 px-3">الشخص</th>
                      <th className="text-right py-2 px-3">المبلغ</th>
                      <th className="text-right py-2 px-3">الاتجاه</th>
                      <th className="text-right py-2 px-3">السبب</th>
                      <th className="text-right py-2 px-3">الحالة</th>
                    </tr>
                  </thead>
                  <tbody>
                    {debtList.map((d: any, i: number) => (
                      <tr key={i} className="border-b border-border/50">
                        <td className="py-2 px-3">{d.person}</td>
                        <td className="py-2 px-3 font-medium">{d.amount} ر.س</td>
                        <td className="py-2 px-3">{d.direction === "i_owe" ? "↑ عليّ" : "↓ لي"}</td>
                        <td className="py-2 px-3 text-muted-foreground">{d.reason}</td>
                        <td className="py-2 px-3">{d.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="alerts">
          {alerts?.alerts ? (
            <Card className="border-yellow-500/30 bg-yellow-500/5">
              <CardContent className="p-4">
                <p className="text-sm whitespace-pre-wrap leading-relaxed">{alerts.alerts}</p>
              </CardContent>
            </Card>
          ) : <EmptyState message="لا توجد تنبيهات" />}
        </TabsContent>
      </Tabs>

      <Dialog open={paymentDialog} onOpenChange={setPaymentDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>تسجيل دفعة</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>الشخص</Label><Input value={payForm.person} onChange={e => setPayForm(p => ({ ...p, person: e.target.value }))} /></div>
            <div><Label>المبلغ</Label><Input type="number" value={payForm.amount} onChange={e => setPayForm(p => ({ ...p, amount: e.target.value }))} /></div>
            <div>
              <Label>الاتجاه</Label>
              <Select value={payForm.direction} onValueChange={v => setPayForm(p => ({ ...p, direction: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="i_owe">عليّ</SelectItem>
                  <SelectItem value="owed_to_me">لي</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => recordPayment.mutate({ ...payForm, amount: Number(payForm.amount) })}>حفظ</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
