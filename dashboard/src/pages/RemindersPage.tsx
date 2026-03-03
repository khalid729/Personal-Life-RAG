import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, MoreHorizontal, MapPin, Pin, RefreshCw } from "lucide-react";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { formatDistanceToNow, parseISO } from "date-fns";
import { ar } from "date-fns/locale";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/20 text-yellow-400",
  done: "bg-green-500/20 text-green-400",
  snoozed: "bg-blue-500/20 text-blue-400",
  cancelled: "bg-gray-500/20 text-gray-400",
};

const PRIORITY_COLORS = ["", "bg-gray-400", "bg-blue-400", "bg-yellow-400", "bg-orange-400", "bg-red-500"];

export default function RemindersPage() {
  const [status, setStatus] = useState("pending");
  const [snoozeDialog, setSnoozeDialog] = useState<any>(null);
  const [snoozeUntil, setSnoozeUntil] = useState("");
  const qc = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["reminders", status],
    queryFn: async () => {
      const res = await apiClient(status === "all" ? "/reminders" : `/reminders?status=${status}`);
      return res.json();
    },
    staleTime: 30000,
    retry: false,
  });

  const action = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/reminders/action", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["reminders"] }); toast.success("تم تحديث التذكير"); },
    onError: (e: any) => toast.error(e.message),
  });

  const mergeDuplicates = useMutation({
    mutationFn: async () => { const res = await apiClient("/reminders/merge-duplicates", { method: "POST" }); return res.json(); },
    onSuccess: (d) => { toast.success(`تم الدمج: ${JSON.stringify(d)}`); qc.invalidateQueries({ queryKey: ["reminders"] }); },
    onError: (e: any) => toast.error(e.message),
  });

  const isTextResponse = typeof data?.reminders === "string";
  const reminders = Array.isArray(data?.reminders) ? data.reminders : [];

  const getRelativeDate = (dt: string) => {
    try {
      return formatDistanceToNow(parseISO(dt), { addSuffix: true, locale: ar });
    } catch { return dt; }
  };

  return (
    <PageContainer
      title="التذكيرات"
      actions={
        <Button variant="outline" size="sm" onClick={() => mergeDuplicates.mutate()}>
          <RefreshCw className="w-4 h-4 ml-1" /> دمج المكررات
        </Button>
      }
    >
      <Tabs value={status} onValueChange={setStatus}>
        <TabsList>
          <TabsTrigger value="all">الكل</TabsTrigger>
          <TabsTrigger value="pending">معلق</TabsTrigger>
          <TabsTrigger value="done">منتهي</TabsTrigger>
          <TabsTrigger value="snoozed">مؤجل</TabsTrigger>
        </TabsList>
      </Tabs>

      {isLoading && <LoadingSkeleton />}
      {error && <p className="text-destructive text-sm">{(error as any).message}</p>}

      {!isLoading && isTextResponse && (
        <div className="bg-card border border-border rounded-lg p-4">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{data.reminders}</p>
        </div>
      )}

      {!isLoading && !isTextResponse && reminders.length === 0 && <EmptyState message="لا توجد تذكيرات" />}

      <div className="space-y-3">
        {reminders.map((r: any, i: number) => (
          <div key={i} className="bg-card border border-border rounded-lg p-4 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-sm">{r.title}</h3>
                  {r.persistent && <Pin className="w-3 h-3 text-muted-foreground" />}
                </div>
                {r.due_date && (
                  <p className={`text-xs mt-1 ${
                    new Date(r.due_date) < new Date() ? "text-destructive" :
                    new Date(r.due_date).toDateString() === new Date().toDateString() ? "text-orange-400" :
                    "text-green-400"
                  }`}>
                    {getRelativeDate(r.due_date)}
                  </p>
                )}
                {r.description && <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{r.description}</p>}
                <div className="flex items-center gap-2 flex-wrap mt-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[r.status] || ""}`}>{r.status}</span>
                  {r.reminder_type && <Badge variant="outline" className="text-xs">{r.reminder_type}</Badge>}
                  {r.recurrence && <Badge variant="outline" className="text-xs">{r.recurrence}</Badge>}
                  {r.priority && (
                    <span className="flex gap-0.5">
                      {Array.from({ length: r.priority }).map((_, j) => (
                        <span key={j} className={`w-1.5 h-1.5 rounded-full ${PRIORITY_COLORS[r.priority]}`} />
                      ))}
                    </span>
                  )}
                  {r.location_place && (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <MapPin className="w-3 h-3" />{r.location_place}
                    </span>
                  )}
                </div>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0">
                    <MoreHorizontal className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onClick={() => action.mutate({ title: r.title, action: "done" })}>
                    ✅ إنهاء
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => { setSnoozeDialog(r); setSnoozeUntil(""); }}>
                    ⏰ تأجيل
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => action.mutate({ title: r.title, action: "cancel" })}>
                    ❌ إلغاء
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        ))}
      </div>

      {/* Snooze dialog */}
      <Dialog open={!!snoozeDialog} onOpenChange={() => setSnoozeDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>تأجيل التذكير</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              {["30min", "1hr", "3hr", "tomorrow"].map((opt) => (
                <Button key={opt} variant="outline" size="sm"
                  onClick={() => {
                    const d = new Date();
                    if (opt === "30min") d.setMinutes(d.getMinutes() + 30);
                    else if (opt === "1hr") d.setHours(d.getHours() + 1);
                    else if (opt === "3hr") d.setHours(d.getHours() + 3);
                    else { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0); }
                    setSnoozeUntil(d.toISOString());
                  }}
                >
                  {opt === "30min" ? "30 دقيقة" : opt === "1hr" ? "ساعة" : opt === "3hr" ? "3 ساعات" : "غداً"}
                </Button>
              ))}
            </div>
            <div>
              <Label className="text-xs">وقت مخصص</Label>
              <Input type="datetime-local" value={snoozeUntil} onChange={e => setSnoozeUntil(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => {
              if (snoozeUntil) {
                action.mutate({ title: snoozeDialog.title, action: "snooze", snooze_until: snoozeUntil });
                setSnoozeDialog(null);
              }
            }} disabled={!snoozeUntil}>تأجيل</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
