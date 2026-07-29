import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { QueryResponse, SearchMode } from "@/api/types";

export function useAsk() {
  return useMutation({
    mutationFn: (vars: { question: string; mode: SearchMode; top_k: number }) =>
      api.post<QueryResponse>("/query", vars),
  });
}