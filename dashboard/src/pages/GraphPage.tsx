import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

const ENTITY_TYPES = ["Person","Project","Task","Expense","Debt","Reminder","Company","Item","Knowledge","Topic","Tag","Sprint","Idea","FocusSession","Place","File"];

const ENTITY_COLORS: Record<string, string> = {
  Person: "#4A90D9", Project: "#E8943A", Task: "#5CB85C", Expense: "#D9534F",
  Debt: "#F0AD4E", Reminder: "#9B59B6", Company: "#3498DB", Item: "#1ABC9C",
  Knowledge: "#2ECC71", Topic: "#95A5A6", Tag: "#BDC3C7", Sprint: "#E74C3C",
  Idea: "#F39C12", FocusSession: "#8E44AD", Place: "#16A085", File: "#607D8B",
};

export default function GraphPage() {
  const [entityType, setEntityType] = useState("all");
  const [centerEntity, setCenterEntity] = useState("");
  const [hops, setHops] = useState(2);
  const [limit, setLimit] = useState(500);
  const [queryParams, setQueryParams] = useState<Record<string, any>>({});
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [ForceGraph, setForceGraph] = useState<any>(null);
  const fgRef = useRef<any>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [wrapSize, setWrapSize] = useState({ w: 800, h: 550 });

  // Dynamic import — avoids SSR & ensures the lib loads cleanly
  useEffect(() => {
    import("react-force-graph-2d").then((mod) => setForceGraph(() => mod.default));
  }, []);

  // Measure container
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setWrapSize({ w: Math.floor(width), h: Math.floor(height) });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Block page scroll when pointer is inside the graph — must stop propagation
  // so the scrollable <main> in AppLayout never receives the wheel event.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const stop = (e: WheelEvent) => { e.stopPropagation(); };
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  const buildPath = useCallback(() => {
    const p = new URLSearchParams();
    if (entityType !== "all") p.set("entity_type", entityType);
    if (centerEntity) { p.set("center", centerEntity); p.set("hops", String(hops)); }
    p.set("limit", String(limit));
    return `/graph/export?${p.toString()}`;
  }, [entityType, centerEntity, hops, limit]);

  const { data: graphData, isLoading } = useQuery({
    queryKey: ["graph", queryParams],
    queryFn: async () => { const r = await apiClient(buildPath()); return r.json(); },
    staleTime: 300000, retry: false,
    enabled: Object.keys(queryParams).length > 0,
  });
  const { data: schema } = useQuery({
    queryKey: ["graph-schema"],
    queryFn: async () => { const r = await apiClient("/graph/schema"); return r.json(); },
    staleTime: 300000, retry: false,
  });
  const { data: stats } = useQuery({
    queryKey: ["graph-stats"],
    queryFn: async () => { const r = await apiClient("/graph/stats"); return r.json(); },
    staleTime: 300000, retry: false,
  });

  const rawNodes: any[] = Array.isArray(graphData?.nodes) ? graphData.nodes : [];
  const rawEdges: any[] = Array.isArray(graphData?.edges) ? graphData.edges : [];

  const forceData = useMemo(() => {
    if (!rawNodes.length) return { nodes: [], links: [] };
    const ids = new Set(rawNodes.map(n => n.id));
    const deg: Record<number, number> = {};
    const links = rawEdges
      .filter(e => ids.has(e.source) && ids.has(e.target))
      .map(e => {
        deg[e.source] = (deg[e.source] || 0) + 1;
        deg[e.target] = (deg[e.target] || 0) + 1;
        return { source: e.source, target: e.target, label: e.type || "" };
      });
    const nodes = rawNodes.map(n => ({
      id: n.id,
      name: n.properties?.title || n.properties?.name || n.label || `#${n.id}`,
      nodeType: n.type,
      properties: n.properties,
      color: ENTITY_COLORS[n.type] || "#4A90D9",
      val: Math.max(2, (deg[n.id] || 0) + 1),
    }));
    return { nodes, links };
  }, [rawNodes, rawEdges]);

  // Configure forces and zoom to fit once after data loads
  useEffect(() => {
    if (forceData.nodes.length && fgRef.current) {
      // Stronger repulsion so nodes spread apart visibly
      fgRef.current.d3Force("charge")?.strength(-150);
      fgRef.current.d3Force("link")?.distance(80);
      fgRef.current.d3ReheatSimulation?.();
      const t = setTimeout(() => fgRef.current?.zoomToFit?.(400, 40), 2500);
      return () => clearTimeout(t);
    }
  }, [forceData]);

  const onNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    fgRef.current?.centerAt?.(node.x, node.y, 300);
    fgRef.current?.zoom?.(6, 300);
  }, []);

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]" dir="rtl">
      {/* Controls bar */}
      <div className="flex items-center gap-2 flex-wrap px-4 py-3 border-b border-border bg-card shrink-0">
        <div>
          <Label className="text-xs">نوع الكيان</Label>
          <Select value={entityType} onValueChange={setEntityType}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">الكل</SelectItem>
              {ENTITY_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">كيان مركزي</Label>
          <Input value={centerEntity} onChange={e => setCenterEntity(e.target.value)} placeholder="اسم" className="w-36" />
        </div>
        <div>
          <Label className="text-xs">قفزات</Label>
          <Input type="number" value={hops} onChange={e => setHops(Number(e.target.value))} className="w-16" min={1} max={5} />
        </div>
        <div>
          <Label className="text-xs">حد</Label>
          <Input type="number" value={limit} onChange={e => setLimit(Number(e.target.value))} className="w-20" />
        </div>
        <Button size="sm" onClick={() => setQueryParams({ entityType, centerEntity, hops, limit, ts: Date.now() })}>تحميل</Button>
        {forceData.nodes.length > 0 && (
          <Button size="sm" variant="outline" onClick={() => fgRef.current?.zoomToFit?.(300, 60)}>ملائمة</Button>
        )}
        {forceData.nodes.length > 0 && (
          <span className="text-xs text-muted-foreground mr-auto">{forceData.nodes.length} عقدة · {forceData.links.length} علاقة</span>
        )}
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph canvas — full remaining space */}
        <div ref={wrapRef} className="flex-1 bg-[#0d1117] relative" style={{ touchAction: "none" }}>
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">جاري التحميل...</div>
          )}

          {!isLoading && !forceData.nodes.length && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">
              <div className="text-center"><p className="text-4xl mb-3">🕸</p><p>اضغط "تحميل"</p></div>
            </div>
          )}

          {ForceGraph && forceData.nodes.length > 0 && (
            <ForceGraph
              ref={fgRef}
              width={wrapSize.w}
              height={wrapSize.h}
              graphData={forceData}
              /* Node appearance */
              nodeLabel="name"
              nodeColor="color"
              nodeRelSize={6}
              nodeVal="val"
              /* Labels drawn on canvas */
              nodeCanvasObjectMode={() => "after"}
              nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                if (globalScale < 1.2) return; // hide labels when zoomed out
                const label = (node.name || "").slice(0, 28);
                const fontSize = 12 / globalScale;
                ctx.font = `${fontSize}px sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillStyle = "rgba(220,220,220,0.9)";
                const r = Math.sqrt(node.val || 2) * 6;
                ctx.fillText(label, node.x, node.y + r / globalScale + fontSize);
              }}
              onNodeClick={onNodeClick}
              onNodeDragEnd={(node: any) => { node.fx = node.x; node.fy = node.y; }}
              /* Links */
              linkColor={() => "rgba(255,255,255,0.1)"}
              linkWidth={1}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              linkDirectionalArrowColor={() => "rgba(255,255,255,0.3)"}
              linkLabel="label"
              linkCurvature={0.15}
              /* Behaviour */
              backgroundColor="#0d1117"
              cooldownTicks={200}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
              warmupTicks={80}
            />
          )}
        </div>

        {/* Side panel */}
        <div className="w-64 shrink-0 border-s border-border bg-card overflow-y-auto p-3 space-y-4">
          {selectedNode ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-xs flex items-center justify-between">
                  تفاصيل
                  <Button variant="ghost" size="sm" className="h-5 px-1 text-xs" onClick={() => setSelectedNode(null)}>✕</Button>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs space-y-1.5">
                <p className="font-bold text-sm break-all">{selectedNode.name}</p>
                <Badge style={{ background: `${ENTITY_COLORS[selectedNode.nodeType]}22`, color: ENTITY_COLORS[selectedNode.nodeType] }} className="text-xs">{selectedNode.nodeType}</Badge>
                {selectedNode.properties && Object.entries(selectedNode.properties)
                  .filter(([k]) => k !== "__graphid__")
                  .map(([k, v]) => (
                    <div key={k}>
                      <span className="text-muted-foreground">{k}: </span>
                      <span className="break-all">{String(v).slice(0, 120)}</span>
                    </div>
                  ))}
              </CardContent>
            </Card>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-4">اضغط عقدة لعرض تفاصيلها</p>
          )}

          {schema && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-xs">المخطط</CardTitle></CardHeader>
              <CardContent className="text-xs space-y-1">
                <p className="text-muted-foreground mb-2">{stats?.total_nodes || 0} عقدة · {stats?.total_edges || 0} علاقة</p>
                {schema.node_labels && Object.entries(schema.node_labels)
                  .sort(([, a], [, b]) => (b as number) - (a as number))
                  .map(([label, count]) => (
                    <div key={label} className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: ENTITY_COLORS[label] || "#888" }} />
                      <span className="flex-1">{label}</span>
                      <span className="text-muted-foreground">{String(count)}</span>
                    </div>
                  ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
