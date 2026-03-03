import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageContainer, LoadingSkeleton, EmptyState } from "@/components/PageContainer";
import { apiClient } from "@/config";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Search } from "lucide-react";

export default function KnowledgePage() {
  const [topic, setTopic] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["knowledge", topic],
    queryFn: async () => {
      const q = topic ? `?topic=${encodeURIComponent(topic)}` : "";
      const res = await apiClient(`/knowledge${q}`);
      return res.json();
    },
    staleTime: 30000,
    retry: false,
  });

  const isTextResponse = typeof data?.knowledge === "string";
  const items: any[] = Array.isArray(data?.knowledge) ? data.knowledge : [];

  return (
    <PageContainer title="قاعدة المعرفة">
      <div className="relative">
        <Search className="absolute right-3 top-2.5 w-4 h-4 text-muted-foreground" />
        <Input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="تصفية حسب الموضوع..."
          className="pr-9"
        />
      </div>

      {isLoading && <LoadingSkeleton />}

      {!isLoading && isTextResponse && (
        <div className="bg-card border border-border rounded-lg p-4">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{data.knowledge}</p>
        </div>
      )}

      {!isLoading && !isTextResponse && items.length === 0 && <EmptyState message="لا توجد معلومات" />}

      <div className="space-y-3">
        {items.map((item: any, i: number) => (
          <div key={i} className="bg-card border border-border rounded-lg p-4 space-y-2">
            {item.title && <h3 className="font-semibold text-sm">{item.title}</h3>}
            {item.content && <p className="text-sm text-muted-foreground leading-relaxed">{item.content}</p>}
            <div className="flex gap-2 flex-wrap">
              {item.category && <Badge variant="outline" className="text-xs">{item.category}</Badge>}
              {item.source && <Badge variant="secondary" className="text-xs">{item.source}</Badge>}
              {item.topic && <Badge className="text-xs">{item.topic}</Badge>}
            </div>
          </div>
        ))}
      </div>
    </PageContainer>
  );
}
