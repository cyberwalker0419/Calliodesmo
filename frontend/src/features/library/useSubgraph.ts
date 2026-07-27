import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { SubgraphResponse } from "@/api/types";

export function useSubgraph(seeds: string[], hops: number, limit: number) {
  return useQuery({
    queryKey: ["subgraph", seeds, hops, limit],
    queryFn: () =>
      api.get<SubgraphResponse>("/library/subgraph", {
        seeds: seeds.join(","),
        hops,
        limit,
      }),
    enabled: seeds.length > 0,
  });
}