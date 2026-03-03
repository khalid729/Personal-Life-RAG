import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { Database, RotateCcw } from "lucide-react";

export default function BackupPage() {
  const [confirmRestore, setConfirmRestore] = useState<string | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["backups"],
    queryFn: async () => { const res = await apiClient("/backup/list"); return res.json(); },
    staleTime: 30000,
    retry: false,
  });

  const createBackup = useMutation({
    mutationFn: async () => { const res = await apiClient("/backup/create", { method: "POST" }); return res.json(); },
    onSuccess: (d) => { toast.success(`تم إنشاء النسخة الاحتياطية: ${d.path || ""}`); refetch(); },
    onError: (e: any) => toast.error(e.message),
  });

  const restoreBackup = useMutation({
    mutationFn: async (ts: string) => { const res = await apiClient(`/backup/restore/${ts}`, { method: "POST" }); return res.json(); },
    onSuccess: () => { toast.success("تم الاستعادة بنجاح"); setConfirmRestore(null); },
    onError: (e: any) => toast.error(e.message),
  });

  const backups: any[] = Array.isArray(data?.backups) ? data.backups : [];

  return (
    <PageContainer
      title="النسخ الاحتياطي"
      actions={
        <Button size="sm" onClick={() => createBackup.mutate()} disabled={createBackup.isPending}>
          <Database className="w-4 h-4 ml-1" />
          {createBackup.isPending ? "جاري الإنشاء..." : "إنشاء نسخة احتياطية"}
        </Button>
      }
    >
      {isLoading && <LoadingSkeleton />}
      {!isLoading && backups.length === 0 && <EmptyState message="لا توجد نسخ احتياطية" />}

      <div className="space-y-3">
        {backups.map((b: any, i: number) => (
          <Card key={i}>
            <CardContent className="p-4 flex items-center justify-between">
              <div>
                <p className="font-medium text-sm">{b.timestamp || b.path}</p>
                {b.size && <p className="text-xs text-muted-foreground">{b.size}</p>}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmRestore(b.timestamp)}
                className="gap-2"
              >
                <RotateCcw className="w-3 h-3" /> استعادة
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {confirmRestore && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setConfirmRestore(null)}>
          <div className="bg-card border border-border rounded-lg p-6 space-y-4 max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="font-semibold">تأكيد الاستعادة</h3>
            <p className="text-sm text-muted-foreground">هل أنت متأكد من استعادة النسخة الاحتياطية؟ سيتم الكتابة فوق البيانات الحالية.</p>
            <div className="flex gap-2">
              <Button variant="destructive" onClick={() => restoreBackup.mutate(confirmRestore)}>نعم، استعادة</Button>
              <Button variant="outline" onClick={() => setConfirmRestore(null)}>إلغاء</Button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
