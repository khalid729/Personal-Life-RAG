import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search } from "lucide-react";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("auto");
  const [limit, setLimit] = useState("5");
  const [submitted, setSubmitted] = useState(false);
  const [searchParams, setSearchParams] = useState({ query: "", source: "auto", limit: 5 });

  const { data, isLoading, error } = useQuery({
    queryKey: ["search", searchParams],
    queryFn: async () => {
      const res = await apiClient("/search", {
        method: "POST",
        body: JSON.stringify(searchParams),
      });
      return res.json();
    },
    enabled: submitted && !!searchParams.query,
    staleTime: 0,
    retry: false,
  });

  const handleSearch = () => {
    setSearchParams({ query, source, limit: Number(limit) });
    setSubmitted(true);
  };

  const results = Array.isArray(data?.results) ? data.results : [];

  return (
    <PageContainer title="البحث" subtitle="ابحث في قاعدة المعرفة">
      <div className="flex gap-2 flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute right-3 top-2.5 w-4 h-4 text-muted-foreground" />
          <Input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="ابحث في قاعدة المعرفة..."
            className="pr-9"
          />
        </div>
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">تلقائي</SelectItem>
            <SelectItem value="vector">Vector</SelectItem>
            <SelectItem value="graph">Graph</SelectItem>
          </SelectContent>
        </Select>
        <Input
          type="number"
          value={limit}
          onChange={e => setLimit(e.target.value)}
          className="w-20"
          placeholder="عدد"
        />
        <Button onClick={handleSearch} disabled={!query}>بحث</Button>
      </div>

      {data?.source_used && (
        <p className="text-xs text-muted-foreground">المصدر المستخدم: <Badge variant="outline">{data.source_used}</Badge></p>
      )}

      {isLoading && <LoadingSkeleton />}
      {error && <p className="text-destructive text-sm">{(error as any).message}</p>}
      {submitted && !isLoading && results.length === 0 && <EmptyState message="لا توجد نتائج" />}

      <div className="space-y-3">
        {results.map((r: any, i: number) => (
          <Card key={i}>
            <CardContent className="p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm leading-relaxed flex-1">{r.text}</p>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {r.score !== undefined && (
                    <Badge variant="secondary" className="text-xs">{Math.round(r.score * 100)}%</Badge>
                  )}
                  {r.source && <Badge variant="outline" className="text-xs">{r.source}</Badge>}
                </div>
              </div>
              {r.metadata && Object.keys(r.metadata).length > 0 && (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">البيانات الوصفية</summary>
                  <div className="mt-1 space-y-0.5">
                    {Object.entries(r.metadata).map(([k, v]) => (
                      <p key={k}><span className="font-medium">{k}:</span> {String(v)}</p>
                    ))}
                  </div>
                </details>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </PageContainer>
  );
}
