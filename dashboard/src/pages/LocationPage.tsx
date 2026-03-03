import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { MapPin, Plus, Trash2, Satellite, Map, Pentagon, X, Check } from "lucide-react";

const PLACE_TYPES = ["بقالة","صيدلية","مطعم","كافيه","مول","مسجد","بنزينة","بنك","مستشفى","مدرسة","حديقة","مغسلة","مكتبة","منزل","عمل","أخرى"];

export default function LocationPage() {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<any>(null);
  const tileLayerRef = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const circlesRef = useRef<any[]>([]);

  // Fence drawing state
  const fencePointsRef = useRef<any[]>([]); // L.LatLng[]
  const fenceTempMarkersRef = useRef<any[]>([]);
  const fencePolylineRef = useRef<any>(null);
  const fencePolygonRef = useRef<any>(null);

  const [isSatellite, setIsSatellite] = useState(false);
  const [drawingFence, setDrawingFence] = useState(false);
  const [fencePointCount, setFencePointCount] = useState(0);
  const [addDialog, setAddDialog] = useState(false);
  const [fenceDialog, setFenceDialog] = useState(false);
  const [fenceName, setFenceName] = useState("");
  const [fenceType, setFenceType] = useState("منزل");
  const [form, setForm] = useState({ name: "", lat: "24.7136", lon: "46.6753", radius: "150", place_type: "منزل", address: "" });
  const qc = useQueryClient();

  const { data: places } = useQuery({
    queryKey: ["places"],
    queryFn: async () => { const res = await apiClient("/location/places"); return res.json(); },
    staleTime: 60000, retry: false,
  });

  const { data: currentLocation } = useQuery({
    queryKey: ["current-location"],
    queryFn: async () => { const res = await apiClient("/location/current"); return res.json(); },
    staleTime: 60000, retry: false,
  });

  const savePlace = useMutation({
    mutationFn: async (body: any) => {
      const res = await apiClient("/location/places", { method: "POST", body: JSON.stringify(body) });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["places"] }); toast.success("تم حفظ المكان"); setAddDialog(false); setFenceDialog(false); },
    onError: (e: any) => toast.error(e.message),
  });

  const deletePlace = useMutation({
    mutationFn: async (name: string) => {
      const res = await apiClient(`/location/places/${encodeURIComponent(name)}`, { method: "DELETE" });
      return res.json();
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["places"] }); toast.success("تم حذف المكان"); },
    onError: (e: any) => toast.error(e.message),
  });

  // Initialize Leaflet map
  useEffect(() => {
    if (!mapRef.current || leafletMapRef.current) return;

    const initMap = async () => {
      const L = (await import("leaflet")).default;
      await import("leaflet/dist/leaflet.css");

      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const map = L.map(mapRef.current!, { zoomControl: true });

      tileLayerRef.current = L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { attribution: "© OpenStreetMap" }
      ).addTo(map);

      map.setView([24.7136, 46.6753], 6);

      // Click handler — context-aware
      map.on("click", (e: any) => {
        // If drawing fence mode
        if ((map as any)._drawingFence) {
          const L2 = (map as any)._L;
          fencePointsRef.current.push(e.latlng);

          // Add a small dot marker
          const dot = L2.circleMarker(e.latlng, {
            radius: 5, color: "#f59e0b", fillColor: "#f59e0b", fillOpacity: 1, weight: 2,
          }).addTo(map);
          fenceTempMarkersRef.current.push(dot);

          // Draw/update polyline preview
          if (fencePolylineRef.current) map.removeLayer(fencePolylineRef.current);
          if (fencePointsRef.current.length >= 2) {
            fencePolylineRef.current = L2.polyline(fencePointsRef.current, {
              color: "#f59e0b", dashArray: "6,4", weight: 2,
            }).addTo(map);
          }

          // If 3+ points, show polygon preview
          if (fencePointsRef.current.length >= 3) {
            if (fencePolygonRef.current) map.removeLayer(fencePolygonRef.current);
            fencePolygonRef.current = L2.polygon(fencePointsRef.current, {
              color: "#f59e0b", fillColor: "#f59e0b", fillOpacity: 0.15, weight: 2, dashArray: "6,4",
            }).addTo(map);
          }

          setFencePointCount(fencePointsRef.current.length);
          return;
        }

        // Normal mode — open add dialog
        setForm(p => ({ ...p, lat: e.latlng.lat.toFixed(6), lon: e.latlng.lng.toFixed(6) }));
        setAddDialog(true);
      });

      leafletMapRef.current = { map, L };
      (map as any)._L = L;
      (map as any)._drawingFence = false;
    };

    initMap().catch(console.error);

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.map.remove();
        leafletMapRef.current = null;
      }
    };
  }, []);

  // Toggle satellite
  useEffect(() => {
    if (!leafletMapRef.current) return;
    const { map, L } = leafletMapRef.current;
    if (tileLayerRef.current) map.removeLayer(tileLayerRef.current);
    const url = isSatellite
      ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
      : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
    tileLayerRef.current = L.tileLayer(url, { attribution: isSatellite ? "© Esri" : "© OpenStreetMap" }).addTo(map);
  }, [isSatellite]);

  // Render markers / circles
  useEffect(() => {
    if (!leafletMapRef.current) return;
    const { map, L } = leafletMapRef.current;

    markersRef.current.forEach(m => map.removeLayer(m));
    circlesRef.current.forEach(c => map.removeLayer(c));
    markersRef.current = [];
    circlesRef.current = [];

    const placeList: any[] = Array.isArray(places?.places) ? places.places : [];

    placeList.forEach((p: any) => {
      if (!p.lat || !p.lon) return;
      const marker = L.marker([p.lat, p.lon]).addTo(map).bindPopup(`
        <div dir="rtl" style="font-family:'IBM Plex Sans Arabic',sans-serif;min-width:140px">
          <strong>${p.name}</strong><br/>
          ${p.place_type ? `<span style="color:#888">${p.place_type}</span><br/>` : ""}
          ${p.address ? `<span style="font-size:12px;color:#888">${p.address}</span><br/>` : ""}
          ${p.radius ? `<span style="font-size:12px">نطاق: ${p.radius}م</span>` : ""}
          ${p.fence ? `<span style="font-size:12px;color:#f59e0b"> • فنس مرسوم</span>` : ""}
        </div>
      `);

      const circle = L.circle([p.lat, p.lon], {
        radius: p.radius || 150, color: "#4A90D9", fillColor: "#4A90D9", fillOpacity: 0.12, weight: 1.5,
      }).addTo(map);

      // Draw fence polygon if exists
      if (p.fence && Array.isArray(p.fence) && p.fence.length >= 3) {
        const fencePoly = L.polygon(p.fence, {
          color: "#f59e0b", fillColor: "#f59e0b", fillOpacity: 0.15, weight: 2,
        }).addTo(map);
        circlesRef.current.push(fencePoly);
      }

      markersRef.current.push(marker);
      circlesRef.current.push(circle);
    });

    if (currentLocation?.position?.lat) {
      const pos = currentLocation.position;
      const pulseIcon = L.divIcon({
        className: "",
        html: `<div style="width:14px;height:14px;background:#4A90D9;border-radius:50%;border:2px solid white;box-shadow:0 0 0 4px rgba(74,144,217,0.3)"></div>`,
        iconSize: [14, 14], iconAnchor: [7, 7],
      });
      const cur = L.marker([pos.lat, pos.lon], { icon: pulseIcon }).addTo(map).bindPopup("موقعك الحالي");
      markersRef.current.push(cur);
    }
  }, [places, currentLocation]);

  // Start fence drawing
  const startFence = () => {
    if (!leafletMapRef.current) return;
    const { map } = leafletMapRef.current;
    // Clear any previous temp drawing
    clearFenceTemp(map);
    (map as any)._drawingFence = true;
    setDrawingFence(true);
    setFencePointCount(0);
    map.getContainer().style.cursor = "crosshair";
  };

  const clearFenceTemp = (map: any) => {
    fenceTempMarkersRef.current.forEach(m => map.removeLayer(m));
    fenceTempMarkersRef.current = [];
    if (fencePolylineRef.current) { map.removeLayer(fencePolylineRef.current); fencePolylineRef.current = null; }
    if (fencePolygonRef.current) { map.removeLayer(fencePolygonRef.current); fencePolygonRef.current = null; }
    fencePointsRef.current = [];
  };

  const cancelFence = () => {
    if (!leafletMapRef.current) return;
    const { map } = leafletMapRef.current;
    clearFenceTemp(map);
    (map as any)._drawingFence = false;
    setDrawingFence(false);
    setFencePointCount(0);
    map.getContainer().style.cursor = "";
  };

  const confirmFence = () => {
    if (fencePointsRef.current.length < 3) {
      toast.error("ضع على الأقل 3 نقاط لرسم الفنس");
      return;
    }
    // Compute centroid
    const pts = fencePointsRef.current;
    const lat = pts.reduce((s: number, p: any) => s + p.lat, 0) / pts.length;
    const lng = pts.reduce((s: number, p: any) => s + p.lng, 0) / pts.length;

    if (!leafletMapRef.current) return;
    const { map } = leafletMapRef.current;
    (map as any)._drawingFence = false;
    map.getContainer().style.cursor = "";
    setDrawingFence(false);
    // Keep polygon visible while dialog is open
    setFenceName("");
    setFenceType("منزل");
    setFenceDialog(true);

    // Store centroid temporarily in form
    setForm(p => ({ ...p, lat: lat.toFixed(6), lon: lng.toFixed(6) }));
  };

  const saveFencePlace = () => {
    if (!fenceName.trim()) { toast.error("أدخل اسم المكان"); return; }
    const pts = fencePointsRef.current.map((p: any) => [p.lat, p.lng]);
    savePlace.mutate({
      name: fenceName,
      lat: Number(form.lat),
      lon: Number(form.lon),
      radius: 0,
      place_type: fenceType,
      fence: pts,
    });
    if (leafletMapRef.current) {
      clearFenceTemp(leafletMapRef.current.map);
    }
  };

  const cancelFenceDialog = () => {
    setFenceDialog(false);
    if (leafletMapRef.current) clearFenceTemp(leafletMapRef.current.map);
  };

  const placeList: any[] = Array.isArray(places?.places) ? places.places : [];

  const zoomToPlace = (lat: number, lon: number) => {
    if (leafletMapRef.current) leafletMapRef.current.map.setView([lat, lon], 16);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-card shrink-0">
        <div className="flex items-center gap-2">
          <MapPin className="w-5 h-5 text-primary" />
          <h1 className="text-lg font-bold">الخريطة والأماكن</h1>
          {placeList.length > 0 && (
            <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{placeList.length} مكان</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant={isSatellite ? "default" : "outline"} size="sm" onClick={() => setIsSatellite(s => !s)} className="gap-1.5">
            {isSatellite ? <Map className="w-4 h-4" /> : <Satellite className="w-4 h-4" />}
            {isSatellite ? "خريطة عادية" : "صور فضائية"}
          </Button>

          {/* Fence drawing controls */}
          {!drawingFence ? (
            <Button variant="outline" size="sm" onClick={startFence} className="gap-1.5 border-amber-500/50 text-amber-500 hover:bg-amber-500/10">
              <Pentagon className="w-4 h-4" /> رسم فنس
            </Button>
          ) : (
            <>
              <span className="text-xs text-amber-500 bg-amber-500/10 border border-amber-500/30 px-2 py-1 rounded-md">
                {fencePointCount} نقطة {fencePointCount >= 3 ? "✓ جاهز" : "— أضف المزيد"}
              </span>
              <Button variant="outline" size="sm" onClick={confirmFence} disabled={fencePointCount < 3} className="gap-1 border-green-500/50 text-green-500 hover:bg-green-500/10">
                <Check className="w-4 h-4" /> تأكيد
              </Button>
              <Button variant="ghost" size="sm" onClick={cancelFence} className="gap-1 text-destructive hover:text-destructive">
                <X className="w-4 h-4" /> إلغاء
              </Button>
            </>
          )}

          <Button size="sm" onClick={() => { setForm({ name: "", lat: "24.7136", lon: "46.6753", radius: "150", place_type: "منزل", address: "" }); setAddDialog(true); }}>
            <Plus className="w-4 h-4 ml-1" /> إضافة مكان
          </Button>
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative" style={{ minHeight: "350px" }}>
        <div ref={mapRef} className="absolute inset-0" />
        <div className="absolute bottom-3 right-3 z-[1000] bg-card/90 border border-border rounded-md px-3 py-1.5 text-xs text-muted-foreground pointer-events-none">
          {drawingFence ? "انقر لإضافة نقاط الفنس — ثم اضغط تأكيد" : "انقر على الخريطة لإضافة مكان"}
        </div>
      </div>

      {/* Places list */}
      {placeList.length > 0 && (
        <div className="max-h-48 overflow-y-auto border-t border-border bg-card shrink-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/60 sticky top-0">
              <tr className="text-muted-foreground">
                <th className="text-right py-2 px-4 font-medium">الاسم</th>
                <th className="text-right py-2 px-4 font-medium">النوع</th>
                <th className="text-right py-2 px-4 font-medium">النطاق</th>
                <th className="text-right py-2 px-4 font-medium">الإحداثيات</th>
                <th className="py-2 px-4" />
              </tr>
            </thead>
            <tbody>
              {placeList.map((p: any, i: number) => (
                <tr key={i} className="border-t border-border/50 hover:bg-muted/30 transition-colors">
                  <td className="py-2 px-4 font-medium">
                    {p.name}
                    {p.fence && <span className="mr-1 text-amber-500 text-xs">• فنس</span>}
                  </td>
                  <td className="py-2 px-4 text-muted-foreground">{p.place_type || "—"}</td>
                  <td className="py-2 px-4 text-muted-foreground">{p.radius ? `${p.radius}م` : "—"}</td>
                  <td className="py-2 px-4 text-muted-foreground text-xs font-mono">
                    {p.lat && p.lon ? (
                      <button onClick={() => zoomToPlace(p.lat, p.lon)} className="text-primary underline">
                        {Number(p.lat).toFixed(4)}, {Number(p.lon).toFixed(4)}
                      </button>
                    ) : "—"}
                  </td>
                  <td className="py-2 px-4">
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive" onClick={() => deletePlace.mutate(p.name)}>
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add place dialog */}
      <Dialog open={addDialog} onOpenChange={setAddDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>إضافة مكان جديد</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>الاسم *</Label>
              <Input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} placeholder="مثال: منزلي، المكتب..." />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>خط العرض (Lat)</Label><Input value={form.lat} onChange={e => setForm(p => ({ ...p, lat: e.target.value }))} /></div>
              <div><Label>خط الطول (Lon)</Label><Input value={form.lon} onChange={e => setForm(p => ({ ...p, lon: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>النطاق (م)</Label><Input type="number" value={form.radius} onChange={e => setForm(p => ({ ...p, radius: e.target.value }))} /></div>
              <div>
                <Label>نوع المكان</Label>
                <select value={form.place_type} onChange={e => setForm(p => ({ ...p, place_type: e.target.value }))} className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm" dir="rtl">
                  {PLACE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div><Label>العنوان</Label><Input value={form.address} onChange={e => setForm(p => ({ ...p, address: e.target.value }))} placeholder="العنوان التفصيلي..." /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialog(false)}>إلغاء</Button>
            <Button onClick={() => savePlace.mutate({ ...form, lat: Number(form.lat), lon: Number(form.lon), radius: Number(form.radius) })} disabled={!form.name || savePlace.isPending}>
              {savePlace.isPending ? "جاري الحفظ..." : "حفظ المكان"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Fence save dialog */}
      <Dialog open={fenceDialog} onOpenChange={cancelFenceDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>حفظ منطقة الفنس</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">تم رسم فنس بـ {fencePointsRef.current.length} نقطة. أدخل اسم المنطقة:</p>
            <div>
              <Label>اسم المنطقة *</Label>
              <Input value={fenceName} onChange={e => setFenceName(e.target.value)} placeholder="مثال: حي النزهة، مبنى العمل..." autoFocus />
            </div>
            <div>
              <Label>نوع المكان</Label>
              <select value={fenceType} onChange={e => setFenceType(e.target.value)} className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm" dir="rtl">
                {PLACE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={cancelFenceDialog}>إلغاء</Button>
            <Button onClick={saveFencePlace} disabled={!fenceName.trim() || savePlace.isPending}>
              {savePlace.isPending ? "جاري الحفظ..." : "حفظ الفنس"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
