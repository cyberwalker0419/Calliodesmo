import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { IngestAccepted, JobOut } from "@/api/types";

/** 上传文档 -> 202 + job_id（异步 ECL job；进度经 useJob 轮询）。 */
export function useIngest() {
  return useMutation({
    mutationFn: async (vars: { file: File }) => {
      const form = new FormData();
      form.append("file", vars.file);
      return api.upload<IngestAccepted>("/ingest", form);
    },
  });
}

const TERMINAL = new Set(["succeeded", "failed"]);

/** 轮询摄入 job 进度；终态（succeeded/failed）自动停轮询。 */
export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<JobOut>(`/jobs/${jobId}`),
    enabled: jobId !== null,
    // 非终态每 1.2s 轮询；终态后 refetchInterval 函数返回 false 停止
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 1200;
    },
  });
}
