import { ChevronDown, ChevronRight, Quote } from "lucide-react";
import { useState } from "react";
import type { QueryResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function AnswerCard({ result }: { result: QueryResponse }) {
  const [open, setOpen] = useState<string | null>(null);
  const chunks = new Map(result.context_chunks.map((c) => [c.chunk_id, c]));

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2">
        <Quote className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium">答案</span>
        <Badge variant="secondary">{result.mode}</Badge>
        {result.model && (
          <span className="text-xs text-muted-foreground" title={result.model}>
            {result.model.split(/[\\/]/).pop()}
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.answer}</p>
      {result.source_chunk_ids.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">来源标注（点击展开证据）</div>
          <div className="flex flex-wrap gap-1.5">
            {result.source_chunk_ids.map((id) => {
              const isOpen = open === id;
              return (
                <button
                  key={id}
                  onClick={() => setOpen(isOpen ? null : id)}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs hover:bg-accent"
                >
                  {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  {id}
                </button>
              );
            })}
          </div>
          {open && chunks.get(open) && (
            <div className={cn("mt-2 rounded-md border bg-muted/40 p-3 text-xs leading-relaxed")}>
              {chunks.get(open)?.content}
            </div>
          )}
        </div>
      )}
    </div>
  );
}