import React, { useState, useRef, useEffect } from "react";
import { Send, Trash2, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/config";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";

interface Message {
  role: "user" | "assistant";
  content: string;
  tool_calls?: string[];
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);

    try {
      const res = await apiClient("/chat/v2", {
        method: "POST",
        body: JSON.stringify({ message: userMsg, session_id: "dashboard" }),
      });
      const text = await res.text();
      let data: any;
      try {
        data = JSON.parse(text);
      } catch {
        data = { reply: text || "..." };
      }
      const toolNames = Array.isArray(data.tool_calls)
        ? data.tool_calls.map((t: any) => (typeof t === "string" ? t : t.name || JSON.stringify(t))).filter(Boolean)
        : [];
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply || data.response || "...",
          tool_calls: toolNames,
        },
      ]);
    } catch (e: any) {
      toast.error(e.message || "خطأ في الاتصال");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `خطأ: ${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const fetchSummary = async () => {
    try {
      const res = await apiClient("/chat/summary?session_id=dashboard");
      const data = await res.json();
      setSummary(data.summary || JSON.stringify(data));
      setSummaryOpen(true);
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]" dir="rtl">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-card shrink-0">
        <Button variant="ghost" size="sm" onClick={() => setMessages([])} className="gap-2">
          <Trash2 className="w-4 h-4" /> مسح المحادثة
        </Button>
        <Button variant="ghost" size="sm" onClick={fetchSummary} className="gap-2">
          <FileText className="w-4 h-4" /> ملخص
        </Button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <div className="text-5xl mb-4">🤖</div>
            <p className="text-sm">ابدأ محادثة مع مساعد RAG الشخصي</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-start" : "justify-end"}`}>
            <div className={`max-w-[75%] px-4 py-3 text-sm ${msg.role === "user" ? "bubble-user" : "bubble-assistant"}`}>
              <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
              {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {msg.tool_calls.map((tool, j) => (
                    <Badge key={j} variant="secondary" className="text-xs">{tool}</Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-end">
            <div className="bubble-assistant px-4 py-3 flex gap-1 items-center">
              <span className="typing-dot w-2 h-2 bg-muted-foreground rounded-full inline-block" />
              <span className="typing-dot w-2 h-2 bg-muted-foreground rounded-full inline-block" />
              <span className="typing-dot w-2 h-2 bg-muted-foreground rounded-full inline-block" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-border bg-card shrink-0">
        <div className="flex gap-2 max-w-3xl mx-auto">
          <Button onClick={sendMessage} disabled={loading || !input.trim()} size="icon">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </Button>
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="اكتب رسالتك..."
            className="flex-1"
            dir="rtl"
          />
        </div>
      </div>

      {/* Summary dialog */}
      <Dialog open={summaryOpen} onOpenChange={setSummaryOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>ملخص المحادثة</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">{summary}</p>
        </DialogContent>
      </Dialog>
    </div>
  );
}
