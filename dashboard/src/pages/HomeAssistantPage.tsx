import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Lightbulb, ToggleLeft, Thermometer, Monitor, Wind,
  ChevronUp, ChevronDown, Tag, Plus, Trash2, Wifi, WifiOff,
} from "lucide-react";
import { cn } from "@/lib/utils";

const DOMAIN_TABS = [
  { key: "", label: "الكل" },
  { key: "light", label: "أنوار" },
  { key: "switch", label: "سويتشات" },
  { key: "climate", label: "مكيفات" },
  { key: "cover", label: "ستائر" },
  { key: "media_player", label: "ميديا" },
  { key: "sensor", label: "سنسورات" },
  { key: "fan", label: "مراوح" },
  { key: "automation", label: "أتمتة" },
];

const DOMAIN_ICONS: Record<string, React.ElementType> = {
  light: Lightbulb,
  switch: ToggleLeft,
  climate: Thermometer,
  cover: ChevronUp,
  media_player: Monitor,
  sensor: Wind,
  fan: Wind,
};

type HAEntity = {
  entity_id: string;
  state: string;
  friendly_name: string;
  domain: string;
  attributes: Record<string, any>;
  last_changed: string;
};

export default function HomeAssistantPage() {
  const [domain, setDomain] = useState("");
  const [search, setSearch] = useState("");
  const [nameDialog, setNameDialog] = useState(false);
  const [nameForm, setNameForm] = useState({ entity_id: "", arabic_name: "" });
  const qc = useQueryClient();

  const { data: statesData, isLoading, error } = useQuery({
    queryKey: ["ha-states", domain],
    queryFn: async () => {
      const params = domain ? `?domain=${domain}` : "";
      const res = await apiClient(`/ha/states${params}`);
      return res.json();
    },
    refetchInterval: 30000,
    retry: false,
  });

  const { data: namesData } = useQuery({
    queryKey: ["ha-names"],
    queryFn: async () => { const res = await apiClient("/ha/names"); return res.json(); },
    staleTime: 60000, retry: false,
  });

  const toggleMut = useMutation({
    mutationFn: async ({ entity_id, domain: d }: { entity_id: string; domain: string }) => {
      const res = await apiClient(`/ha/services/${d}/toggle`, {
        method: "POST",
        body: JSON.stringify({ entity_id }),
      });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ha-states"] }); },
    onError: (e: any) => toast.error(e.message),
  });

  const setTempMut = useMutation({
    mutationFn: async ({ entity_id, temperature }: { entity_id: string; temperature: number }) => {
      const res = await apiClient(`/ha/services/climate/set_temperature`, {
        method: "POST",
        body: JSON.stringify({ entity_id, data: { temperature } }),
      });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ha-states"] }); },
    onError: (e: any) => toast.error(e.message),
  });

  const saveNameMut = useMutation({
    mutationFn: async (body: { entity_id: string; arabic_name: string }) => {
      const res = await apiClient("/ha/names", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ha-names"] });
      toast.success("تم حفظ الاسم");
      setNameDialog(false);
    },
    onError: (e: any) => toast.error(e.message),
  });

  const deleteNameMut = useMutation({
    mutationFn: async (name: string) => {
      const res = await apiClient(`/ha/names/${encodeURIComponent(name)}`, { method: "DELETE" });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ha-names"] }); toast.success("تم الحذف"); },
    onError: (e: any) => toast.error(e.message),
  });

  const entities: HAEntity[] = statesData?.states || [];
  const names: Record<string, string> = namesData?.names || {};
  const connected = !error && entities.length > 0;

  const filtered = entities.filter((e) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      e.friendly_name.toLowerCase().includes(s) ||
      e.entity_id.toLowerCase().includes(s)
    );
  });

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">المنزل الذكي</h1>
          <p className="text-sm text-muted-foreground">Home Assistant — {entities.length} جهاز</p>
        </div>
        <div className="flex items-center gap-3">
          <div className={cn(
            "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium",
            connected ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                      : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
          )}>
            {connected ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
            {connected ? "متصل" : "غير متصل"}
          </div>
          <Button variant="outline" size="sm" onClick={() => setNameDialog(true)}>
            <Tag className="w-4 h-4 ml-1" /> أسماء مخصصة
          </Button>
        </div>
      </div>

      {/* Domain tabs */}
      <div className="flex gap-2 flex-wrap">
        {DOMAIN_TABS.map((t) => (
          <Button
            key={t.key}
            variant={domain === t.key ? "default" : "outline"}
            size="sm"
            onClick={() => setDomain(t.key)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {/* Search */}
      <Input
        placeholder="ابحث عن جهاز..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-sm"
      />

      {/* Loading / Error */}
      {isLoading && <p className="text-muted-foreground">جاري التحميل...</p>}
      {error && <p className="text-red-500">خطأ في الاتصال بـ Home Assistant</p>}

      {/* Device cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((entity) => (
          <DeviceCard
            key={entity.entity_id}
            entity={entity}
            onToggle={() => toggleMut.mutate({ entity_id: entity.entity_id, domain: entity.domain })}
            onSetTemp={(t) => setTempMut.mutate({ entity_id: entity.entity_id, temperature: t })}
          />
        ))}
      </div>

      {filtered.length === 0 && !isLoading && !error && (
        <p className="text-center text-muted-foreground py-8">لا توجد أجهزة</p>
      )}

      {/* Custom Names Dialog */}
      <Dialog open={nameDialog} onOpenChange={setNameDialog}>
        <DialogContent dir="rtl" className="max-w-lg">
          <DialogHeader>
            <DialogTitle>أسماء الأجهزة المخصصة</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 max-h-60 overflow-y-auto">
            {Object.entries(names).map(([ar, eid]) => (
              <div key={ar} className="flex items-center justify-between bg-muted/50 rounded px-3 py-2">
                <span className="text-sm">{ar} → <code className="text-xs">{eid}</code></span>
                <Button variant="ghost" size="icon" onClick={() => deleteNameMut.mutate(ar)}>
                  <Trash2 className="w-4 h-4 text-destructive" />
                </Button>
              </div>
            ))}
            {Object.keys(names).length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-2">لا توجد أسماء مخصصة</p>
            )}
          </div>
          <div className="border-t pt-3 space-y-2">
            <p className="text-sm font-medium">إضافة اسم جديد</p>
            <Input
              placeholder="الاسم العربي (مثل: نور غرفتي)"
              value={nameForm.arabic_name}
              onChange={(e) => setNameForm((f) => ({ ...f, arabic_name: e.target.value }))}
            />
            <Input
              placeholder="معرف الجهاز (مثل: light.mb)"
              value={nameForm.entity_id}
              onChange={(e) => setNameForm((f) => ({ ...f, entity_id: e.target.value }))}
            />
          </div>
          <DialogFooter>
            <Button
              onClick={() => saveNameMut.mutate(nameForm)}
              disabled={!nameForm.arabic_name || !nameForm.entity_id}
            >
              <Plus className="w-4 h-4 ml-1" /> إضافة
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DeviceCard({
  entity,
  onToggle,
  onSetTemp,
}: {
  entity: HAEntity;
  onToggle: () => void;
  onSetTemp: (temp: number) => void;
}) {
  const isOn = entity.state === "on" || entity.state === "playing" || entity.state === "open";
  const Icon = DOMAIN_ICONS[entity.domain] || ToggleLeft;
  const temp = entity.attributes?.temperature || entity.attributes?.current_temperature;

  return (
    <div className={cn(
      "rounded-xl border p-4 transition-all",
      isOn ? "bg-primary/5 border-primary/30" : "bg-card",
    )}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={cn(
            "w-9 h-9 rounded-lg flex items-center justify-center",
            isOn ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground",
          )}>
            <Icon className="w-5 h-5" />
          </div>
          <div>
            <p className="font-medium text-sm leading-tight">{entity.friendly_name}</p>
            <p className="text-xs text-muted-foreground">{entity.entity_id}</p>
          </div>
        </div>
        <span className={cn(
          "text-xs px-2 py-0.5 rounded-full",
          isOn ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
               : "bg-muted text-muted-foreground",
        )}>
          {entity.state}
        </span>
      </div>

      {/* Controls */}
      {entity.domain === "sensor" ? (
        <div className="text-center text-lg font-semibold">
          {entity.state} {entity.attributes?.unit_of_measurement || ""}
        </div>
      ) : entity.domain === "climate" ? (
        <div className="flex items-center justify-between">
          <Button variant="outline" size="icon" className="h-8 w-8"
            onClick={() => temp && onSetTemp(Number(temp) - 1)}>
            <ChevronDown className="w-4 h-4" />
          </Button>
          <span className="text-lg font-semibold">{temp ? `${temp}°` : entity.state}</span>
          <Button variant="outline" size="icon" className="h-8 w-8"
            onClick={() => temp && onSetTemp(Number(temp) + 1)}>
            <ChevronUp className="w-4 h-4" />
          </Button>
        </div>
      ) : entity.domain === "cover" ? (
        <div className="flex gap-2 justify-center">
          <Button variant="outline" size="sm" onClick={onToggle}>
            {isOn ? "أقفل" : "افتح"}
          </Button>
        </div>
      ) : (
        <Button
          variant={isOn ? "default" : "outline"}
          size="sm"
          className="w-full"
          onClick={onToggle}
        >
          {isOn ? "إطفاء" : "تشغيل"}
        </Button>
      )}
    </div>
  );
}
