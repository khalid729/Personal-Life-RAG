import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Search, Plus } from "lucide-react";

export default function InventoryPage() {
  const [searchQ, setSearchQ] = useState("");
  const [addDialog, setAddDialog] = useState(false);
  const [form, setForm] = useState({ name: "", quantity: 1, location: "", category: "", condition: "", brand: "", description: "" });
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["inventory", searchQ],
    queryFn: async () => {
      const q = searchQ ? `?search=${encodeURIComponent(searchQ)}` : "";
      const res = await apiClient(`/inventory${q}`);
      return res.json();
    },
    staleTime: 30000,
    retry: false,
  });

  const addItem = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/inventory/item", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["inventory"] }); toast.success("تم إضافة العنصر"); setAddDialog(false); },
    onError: (e: any) => toast.error(e.message),
  });

  const isTextResponse = typeof data?.items === "string";
  const items: any[] = Array.isArray(data?.items) ? data.items : [];

  return (
    <PageContainer
      title="المخزون"
      actions={<Button size="sm" onClick={() => setAddDialog(true)}><Plus className="w-4 h-4 ml-1" /> إضافة عنصر</Button>}
    >
      <div className="relative">
        <Search className="absolute right-3 top-2.5 w-4 h-4 text-muted-foreground" />
        <Input
          value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
          placeholder="بحث في المخزون..."
          className="pr-9"
        />
      </div>

      {isLoading && <LoadingSkeleton />}

      {!isLoading && isTextResponse && (
        <div className="bg-card border border-border rounded-lg p-4">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{data.items}</p>
        </div>
      )}

      {!isLoading && !isTextResponse && items.length === 0 && <EmptyState message="لا توجد عناصر في المخزون" />}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((item: any, i: number) => (
          <div key={i} className="bg-card border border-border rounded-lg p-4 space-y-2">
            <h3 className="font-semibold text-sm">{item.name}</h3>
            <div className="text-xs text-muted-foreground space-y-1">
              {item.category && <p>الفئة: {item.category}</p>}
              {item.location && <p>الموقع: {item.location}</p>}
              {item.quantity !== undefined && <p>الكمية: {item.quantity}</p>}
              {item.brand && <p>العلامة: {item.brand}</p>}
              {item.condition && <p>الحالة: {item.condition}</p>}
            </div>
          </div>
        ))}
      </div>

      <Dialog open={addDialog} onOpenChange={setAddDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>إضافة عنصر للمخزون</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>الاسم *</Label><Input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>الكمية</Label><Input type="number" value={form.quantity} onChange={e => setForm(p => ({ ...p, quantity: Number(e.target.value) }))} /></div>
              <div><Label>الفئة</Label><Input value={form.category} onChange={e => setForm(p => ({ ...p, category: e.target.value }))} /></div>
              <div><Label>الموقع</Label><Input value={form.location} onChange={e => setForm(p => ({ ...p, location: e.target.value }))} /></div>
              <div><Label>العلامة التجارية</Label><Input value={form.brand} onChange={e => setForm(p => ({ ...p, brand: e.target.value }))} /></div>
            </div>
            <div><Label>الوصف</Label><Textarea value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button onClick={() => addItem.mutate(form)} disabled={!form.name}>إضافة</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
