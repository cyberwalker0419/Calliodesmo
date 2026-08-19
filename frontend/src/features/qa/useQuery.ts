import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { QueryResponse, SearchMode } from "@/api/types";

export type AskVars = {
  question: string;
  mode: SearchMode;
  top_k: number;
  image?: File | null; // 有图 -> multipart /query/with-image；无图 -> JSON /query
};

export function useAsk() {
  return useMutation({
    mutationFn: async (vars: AskVars) => {
      const { question, mode, top_k, image } = vars;
      if (image instanceof File) {
        // 多模态：multipart/form-data 上传图片 + 字段
        const form = new FormData();
        form.append("question", question);
        form.append("mode", mode);
        form.append("top_k", String(top_k));
        form.append("file", image);
        return api.post<QueryResponse>("/query/with-image", form);
      }
      return api.post<QueryResponse>("/query", { question, mode, top_k });
    },
  });
}
