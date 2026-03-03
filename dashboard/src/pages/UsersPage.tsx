import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Users, Copy } from "lucide-react";

export default function UsersPage() {
  const [registerDialog, setRegisterDialog] = useState(false);
  const [form, setForm] = useState({ user_id: "", display_name: "", tg_chat_id: "", graph_name: "", collection_name: "", redis_prefix: "" });
  const [newApiKey, setNewApiKey] = useState("");
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: async () => { const res = await apiClient("/admin/users"); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const registerUser = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/admin/users", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("تم تسجيل المستخدم");
      if (d.api_key) setNewApiKey(d.api_key);
      else setRegisterDialog(false);
    },
    onError: (e: any) => toast.error(e.message),
  });

  const users: any[] = Array.isArray(data?.users) ? data.users : [];

  return (
    <PageContainer
      title="إدارة المستخدمين"
      actions={<Button size="sm" onClick={() => setRegisterDialog(true)}><Users className="w-4 h-4 ml-1" /> تسجيل مستخدم</Button>}
    >
      {isLoading && <LoadingSkeleton />}
      {!isLoading && users.length === 0 && <EmptyState message="لا يوجد مستخدمون" />}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="text-right py-2 px-3">المعرف</th>
              <th className="text-right py-2 px-3">الاسم</th>
              <th className="text-right py-2 px-3">اسم الرسم البياني</th>
              <th className="text-right py-2 px-3">Telegram</th>
              <th className="text-right py-2 px-3">الحالة</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u: any, i: number) => (
              <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                <td className="py-2 px-3 font-mono text-xs">{u.user_id}</td>
                <td className="py-2 px-3">{u.display_name}</td>
                <td className="py-2 px-3 text-muted-foreground">{u.graph_name}</td>
                <td className="py-2 px-3 text-muted-foreground">{u.tg_chat_id || "—"}</td>
                <td className="py-2 px-3">
                  <Badge variant={u.enabled !== false ? "default" : "secondary"} className="text-xs">
                    {u.enabled !== false ? "مفعل" : "معطل"}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={registerDialog} onOpenChange={(o) => { if (!o) { setRegisterDialog(false); setNewApiKey(""); } }}>
        <DialogContent>
          <DialogHeader><DialogTitle>تسجيل مستخدم جديد</DialogTitle></DialogHeader>
          {newApiKey ? (
            <div className="space-y-3">
              <p className="text-sm text-yellow-400 font-medium">⚠️ احفظ مفتاح API هذا، لن يُعرض مرة أخرى</p>
              <div className="flex gap-2">
                <Input value={newApiKey} readOnly className="font-mono text-xs" />
                <Button variant="outline" size="icon" onClick={() => { navigator.clipboard.writeText(newApiKey); toast.success("تم النسخ"); }}>
                  <Copy className="w-4 h-4" />
                </Button>
              </div>
              <Button onClick={() => { setRegisterDialog(false); setNewApiKey(""); }}>إغلاق</Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div><Label>معرف المستخدم *</Label><Input value={form.user_id} onChange={e => setForm(p => ({ ...p, user_id: e.target.value }))} /></div>
              <div><Label>اسم العرض</Label><Input value={form.display_name} onChange={e => setForm(p => ({ ...p, display_name: e.target.value }))} /></div>
              <div><Label>Telegram Chat ID</Label><Input value={form.tg_chat_id} onChange={e => setForm(p => ({ ...p, tg_chat_id: e.target.value }))} /></div>
              <DialogFooter>
                <Button onClick={() => registerUser.mutate(form)} disabled={!form.user_id || registerUser.isPending}>تسجيل</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
