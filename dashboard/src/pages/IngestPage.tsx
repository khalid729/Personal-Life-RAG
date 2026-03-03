import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Upload, Link, FileText } from "lucide-react";

export default function IngestPage() {
  const [textForm, setTextForm] = useState({ text: "", source_type: "note", tags: "", topic: "" });
  const [urlForm, setUrlForm] = useState({ url: "", context: "", tags: "", topic: "" });
  const [result, setResult] = useState<any>(null);

  const ingestText = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/ingest/text", {
        method: "POST",
        body: JSON.stringify({ ...body, tags: body.tags ? body.tags.split(",").map((t: string) => t.trim()) : [] }),
      });
      return res.json();
    },
    onSuccess: (d) => { toast.success("تم استيراد النص"); setResult(d); },
    onError: (e: any) => toast.error(e.message),
  });

  const ingestUrl = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/ingest/url", {
        method: "POST",
        body: JSON.stringify({ ...body, tags: body.tags ? body.tags.split(",").map((t: string) => t.trim()) : [] }),
      });
      return res.json();
    },
    onSuccess: (d) => { toast.success("تم استيراد الرابط"); setResult(d); },
    onError: (e: any) => toast.error(e.message),
  });

  return (
    <PageContainer title="استيراد البيانات" subtitle="أضف معلومات جديدة لقاعدة RAG">
      <Tabs defaultValue="text">
        <TabsList>
          <TabsTrigger value="text" className="gap-2"><FileText className="w-4 h-4" /> نص</TabsTrigger>
          <TabsTrigger value="url" className="gap-2"><Link className="w-4 h-4" /> رابط</TabsTrigger>
        </TabsList>

        <TabsContent value="text" className="space-y-3">
          <div><Label>المحتوى</Label>
            <Textarea rows={6} value={textForm.text} onChange={e => setTextForm(p => ({ ...p, text: e.target.value }))} placeholder="أدخل النص هنا..." />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label>نوع المصدر</Label>
              <Select value={textForm.source_type} onValueChange={v => setTextForm(p => ({ ...p, source_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["note", "conversation", "document", "idea", "fact"].map(t => (
                    <SelectItem key={t} value={t}>{t}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div><Label>الموضوع</Label>
              <Input value={textForm.topic} onChange={e => setTextForm(p => ({ ...p, topic: e.target.value }))} /></div>
          </div>
          <div><Label>الوسوم (مفصولة بفاصلة)</Label>
            <Input value={textForm.tags} onChange={e => setTextForm(p => ({ ...p, tags: e.target.value }))} /></div>
          <Button onClick={() => ingestText.mutate(textForm)} disabled={!textForm.text || ingestText.isPending}>
            {ingestText.isPending ? "جاري الاستيراد..." : "استيراد النص"}
          </Button>
        </TabsContent>

        <TabsContent value="url" className="space-y-3">
          <div><Label>الرابط</Label>
            <Input value={urlForm.url} onChange={e => setUrlForm(p => ({ ...p, url: e.target.value }))} placeholder="https://..." /></div>
          <div><Label>السياق</Label>
            <Textarea rows={3} value={urlForm.context} onChange={e => setUrlForm(p => ({ ...p, context: e.target.value }))} /></div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label>الموضوع</Label><Input value={urlForm.topic} onChange={e => setUrlForm(p => ({ ...p, topic: e.target.value }))} /></div>
            <div><Label>الوسوم</Label><Input value={urlForm.tags} onChange={e => setUrlForm(p => ({ ...p, tags: e.target.value }))} /></div>
          </div>
          <Button onClick={() => ingestUrl.mutate(urlForm)} disabled={!urlForm.url || ingestUrl.isPending}>
            {ingestUrl.isPending ? "جاري الاستيراد..." : "استيراد الرابط"}
          </Button>
        </TabsContent>
      </Tabs>

      {result && (
        <div className="bg-card border border-border rounded-lg p-4 space-y-2">
          <h3 className="font-semibold text-sm">نتيجة الاستيراد</h3>
          <div className="text-xs text-muted-foreground space-y-1">
            {result.chunks_stored !== undefined && <p>القطع المخزنة: {result.chunks_stored}</p>}
            {result.facts_extracted !== undefined && <p>الحقائق المستخرجة: {result.facts_extracted}</p>}
            {result.entities && <p>الكيانات: {Array.isArray(result.entities) ? result.entities.join(", ") : result.entities}</p>}
            {result.status && <p>الحالة: {result.status}</p>}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
