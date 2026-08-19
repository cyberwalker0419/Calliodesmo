/** 后端 API 响应类型（与 src/calliodesmo/api/schemas.py 对齐）。 */

export interface MeResponse {
  user_id: string;
  username: string;
  clearance: "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "SECRET";
  permissions: string[];
  library_scopes: string[];
  team_ids: string[];
  project_ids: string[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserRoleOut {
  role: string;
  scope: string;
}

export interface UserOut {
  id: string;
  username: string;
  email: string | null;
  clearance: string;
  is_active: boolean;
  roles: UserRoleOut[];
  team_ids: string[];
  project_ids: string[];
}

export interface TeamMemberOut {
  user_id: string;
  username: string;
  role_in_team: string;
}

export interface TeamOut {
  id: string;
  name: string;
  description: string;
  members: TeamMemberOut[];
}

export interface ProjectMemberOut {
  user_id: string;
  role: string | null;
  role_in_project: string;
}

export interface ProjectOut {
  id: string;
  name: string;
  description: string;
  team_id: string;
  members: ProjectMemberOut[];
}

export interface ProfileCardOut {
  entity_name: string;
  entity_type: string | null;
  aliases: string[];
  role: string | null;
  organization: string | null;
  associates: string[];
  timespan: string | null;
  description: string;
  narrative: string | null;
  evidence_chunk_ids: string[];
  access_level: string;
  library_scope: string;
}

export interface CommunityOut {
  community_id: string;
  level: number;
  title: string;
  summary: string;
  member_entity_names: string[];
  metadata: Record<string, unknown>;
  access_level: string;
  library_scope: string;
}

export interface CommunityVersionOut {
  id: string;
  community_id: string;
  version: number;
  created_at: string;
  created_by: string | null;
}

export interface EntityBrief {
  name: string;
  type: string | null;
  description: string;
}

export interface RelationOut {
  source: string;
  target: string;
  type: string | null;
  description: string;
}

export interface EntityOut {
  name: string;
  type: string | null;
  description: string;
  source_chunk_ids: string[];
  template_conforming: boolean;
  access_level: string;
  library_scope: string;
  neighbors: EntityBrief[];
  relations: RelationOut[];
}

export interface SubgraphNode {
  name: string;
  type: string | null;
  description: string;
  access_level: string;
}

export interface SubgraphEdge {
  source: string;
  target: string;
  type: string | null;
  description: string;
}

export interface SubgraphResponse {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  expanded_seeds: string[];
  truncated: boolean;
}

export interface QueryResponse {
  answer: string;
  mode: string;
  source_chunk_ids: string[];
  context_chunks: Array<{ chunk_id: string; content: string; score?: number }>;
  model: string;
}

export interface ContributionOut {
  id: string;
  source_user_id: string;
  source_scope: string;
  target_scope: string;
  target_project_id: string | null;
  target_team_id: string | null;
  title: string;
  description: string;
  status: string;
  doc_ids: string[];
  assignee_id: string | null;
  reviewed_by: string | null;
  merged_at: string | null;
  created_at: string;
  version: number;
}

export interface DiffOut {
  new_entities: number;
  new_relations: number;
  chunks: number;
  communities: number;
  conflicts: number;
  // 明细清单（取自 manifest；冲突仅计数，同名不同义明细留 v2）
  entity_names: string[];
  relation_summaries: string[][]; // [source, target, type]
  chunk_ids: string[];
  community_ids: string[];
  // P4.5 Task 6：待审对齐候选对（embedding 复核档，来自 manifest alignment_pending）
  alignment_pending?: AlignmentPending[];
}

/** 待审对齐候选对（P4.5 Task 6）。 */
export interface AlignmentPending {
  pair_id: string;
  source_name: string;
  target_name: string;
  score: number;
  type: string | null;
  source_type: string | null;
  target_type: string | null;
  source_description: string;
  target_description: string;
  status?: "pending" | "approved" | "rejected";
}

/** /collab/{id}/alignment-review/{approve,reject} 响应。 */
export interface AlignmentReviewOut {
  pair_id: string;
  status: "approved" | "rejected";
  source_name?: string | null;
  target_name?: string | null;
}

export interface IngestStats {
  documents: number;
  chunks: number;
  entities: number;
  relations: number;
  communities: number;
  profile_cards: number;
}

export interface IngestAccepted {
  job_id: string;
  status: string;
  filename: string;
}

export type JobStatus = "pending" | "running" | "succeeded" | "failed";

export interface JobOut {
  id: string;
  filename: string;
  status: JobStatus;
  progress: number;
  progress_stage: string | null;
  result: IngestStats | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type SearchMode = "native_rag" | "local" | "global";

export const CLEARANCE_RANK: Record<string, number> = {
  PUBLIC: 0,
  INTERNAL: 1,
  CONFIDENTIAL: 2,
  SECRET: 3,
};

export const PERMISSIONS = {
  INGEST: "ingest",
  QUERY: "query",
  EXPORT: "export",
  PUSH: "push",
  APPROVE: "approve",
  MANAGE_USERS: "manage_users",
  MANAGE_COMMUNITY: "manage_community",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];