import React, { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { CheckCircle, XCircle } from "lucide-react";

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState(localStorage.getItem("api_key") || "");
  const [adminKey, setAdminKey] = useState(localStorage.getItem("admin_key") || "");
  const [baseUrl, setBaseUrl] = useState(localStorage.getItem("api_base_url") || "");
  const [testStatus, setTestStatus] = useState<"idle" | "ok" | "fail">("idle");

  const save = () => {
    localStorage.setItem("api_key", apiKey);
    localStorage.setItem("admin_key", adminKey);
    localStorage.setItem("api_base_url", baseUrl);
    toast.success("تم حفظ الإعدادات");
  };

  const testConnection = async () => {
    try {
      const res = await apiClient("/graph/stats");
      if (res.ok) setTestStatus("ok");
      else setTestStatus("fail");
    } catch {
      setTestStatus("fail");
    }
  };

  return (
    <PageContainer title="الإعدادات">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* API Config */}
        <Card>
          <CardHeader><CardTitle className="text-sm">إعداد الاتصال بـ API</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label>رابط الـ API الأساسي</Label>
              <Input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="http://localhost:8000" />
            </div>
            <div>
              <Label>مفتاح API</Label>
              <Input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="X-API-Key" />
            </div>
            <div>
              <Label>مفتاح المدير (Admin)</Label>
              <Input type="password" value={adminKey} onChange={e => setAdminKey(e.target.value)} placeholder="X-Admin-Key" />
            </div>
            <div className="flex gap-2">
              <Button onClick={save}>حفظ الإعدادات</Button>
              <Button variant="outline" onClick={testConnection} className="gap-2">
                {testStatus === "ok" && <CheckCircle className="w-4 h-4 text-green-500" />}
                {testStatus === "fail" && <XCircle className="w-4 h-4 text-destructive" />}
                اختبار الاتصال
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* System Info */}
        <Card>
          <CardHeader><CardTitle className="text-sm">معلومات النظام</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">المنطقة الزمنية</span><span>UTC+3 (الرياض)</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">العملة</span><span>SAR (ريال سعودي)</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">الإصدار</span><span>1.0.0</span></div>
          </CardContent>
        </Card>

        {/* Config Reference */}
        <Card className="md:col-span-2">
          <CardHeader><CardTitle className="text-sm">مرجع الإعدادات</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              {[
                { title: "الموقع", items: ["enabled: true", "default_radius: 150m", "cooldown_minutes: 5"] },
                { title: "الصلاة", items: ["city: Riyadh", "country: SA", "offset_minutes: 0"] },
                { title: "التلقائي", items: ["enabled: true", "morning: 7:00", "noon: 12:00", "evening: 21:00"] },
                { title: "النسخ الاحتياطي", items: ["enabled: true", "hour: 3", "retention_days: 30"] },
                { title: "الإنتاجية", items: ["pomodoro: 25min", "sprint: 2 weeks", "energy_peak: 9-11am"] },
                { title: "المخزون", items: ["unused_days: 90", "report_top_n: 10"] },
              ].map((section) => (
                <div key={section.title}>
                  <p className="font-semibold mb-1">{section.title}</p>
                  {section.items.map((item) => (
                    <p key={item} className="text-muted-foreground text-xs">{item}</p>
                  ))}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
