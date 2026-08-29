/** 后端 API 响应类型（与 src/calliodesmo/api/schemas.py 对齐）。 */

import {
  CalendarRange,
  FileText,
  KeyRound,
  Lightbulb,
  ListTodo,
  MessageCircleQuestion,
  Network,
  ScanSearch,
  Settings2,
} from "lucide-react";

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
  // P6 Task 11 泛化兼容扩展（后端带默认值，旧响应不破坏）：
  // task_type 为 "ingest" | "analyze"（默认 ingest）；
  // report_id 仅 analyze 终态成功时指向报告行（ingest 恒 null）。
  task_type?: string;
  report_id?: string | null;
}

// ---- P6 分析域（与 src/calliodesmo/api/schemas.py · analysis/schemas.py 逐字段对齐）----

/** 9 类分析任务类型（第一批 5 类可提交；第二批 4 类待 Task 21-22 接线）。 */
export type AnalysisTaskType =
  | "summary"
  | "key_information"
  | "timeline"
  | "entity_recognition"
  | "relation_mapping"
  | "tasks"
  | "concepts"
  | "qa"
  | "custom";

/**
 * 9 类分析元数据（选择器数据源，克隆 AskPanel MODES 范式）：
 * batch=1 为第一批 5 类（可提交）；batch=2 为第二批 4 类，
 * Task 19 依此灰显「即将上线」（后端未注册类型提交即 400）。
 */
export const ANALYSIS_TASK_TYPES: {
  value: AnalysisTaskType;
  label: string;
  icon: typeof FileText;
  batch: 1 | 2;
}[] = [
  { value: "summary", label: "摘要", icon: FileText, batch: 1 },
  { value: "key_information", label: "关键信息", icon: KeyRound, batch: 1 },
  { value: "timeline", label: "时间线", icon: CalendarRange, batch: 1 },
  { value: "entity_recognition", label: "实体识别", icon: ScanSearch, batch: 1 },
  { value: "qa", label: "问答", icon: MessageCircleQuestion, batch: 1 },
  { value: "relation_mapping", label: "关系映射", icon: Network, batch: 2 },
  { value: "tasks", label: "任务", icon: ListTodo, batch: 2 },
  { value: "concepts", label: "概念", icon: Lightbulb, batch: 2 },
  { value: "custom", label: "自定义", icon: Settings2, batch: 2 },
];

/** POST /analysis/tasks 请求体（doc_ids 空 = 全可见范围；qa 需 question）。 */
export interface AnalysisJobRequest {
  task_type: AnalysisTaskType;
  doc_ids?: string[];
  question?: string | null;
  custom?: { instruction: string; schema?: Record<string, unknown> } | null;
  top_k?: number;
}

/** POST /analysis/tasks 202 响应（task_type 回显提交的分析类型）。 */
export interface AnalysisAccepted {
  job_id: string;
  status: string;
  task_type: string;
}

/** 报告公共信封（九字段；payload 按 task_type 判别，逐类对齐 analysis/schemas.py）。 */
export interface AnalysisEnvelope {
  task_type: AnalysisTaskType;
  status: "ok" | "partial" | "failed";
  generated_at: string;
  model: string;
  prompt_version: string;
  usage: Record<string, number>;
  warnings: string[];
  source_chunk_ids: string[];
  payload: Record<string, unknown>;
}

/** 报告历史列表项（GET /analysis/reports 的 items 元素）。 */
export interface ReportListItem {
  id: string;
  task_type: AnalysisTaskType;
  status: string;
  subject_label: string;
  access_level: string;
  library_scope: string;
  model: string;
  created_at: string;
  source_chunk_count: number;
}

/** GET /analysis/reports 响应（total 为过滤后可见总行数，供分页器）。 */
export interface ReportListOut {
  items: ReportListItem[];
  total: number;
}

/** GET /analysis/documents 可见文档聚合项（Task 19 MaterialPicker 数据源）。 */
export interface AnalysisDocumentOut {
  doc_id: string;
  label: string;
  access_level: string;
  chunk_count: number;
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
  ANALYZE: "analyze", // P6：提交 LLM 分析任务（与后端 Permission.ANALYZE 对齐）
  MANAGE_USERS: "manage_users",
  MANAGE_COMMUNITY: "manage_community",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];