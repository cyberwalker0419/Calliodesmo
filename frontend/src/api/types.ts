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

/** 9 类分析任务类型（Task 21-22 接线完成后九类全部可提交）。 */
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
 * 9 类分析元数据（选择器数据源，克隆 AskPanel MODES 范式）。
 * Task 21-22 接线完成后九类全部可提交，「即将上线」批次门控已移除（Task 23）。
 */
export const ANALYSIS_TASK_TYPES: {
  value: AnalysisTaskType;
  label: string;
  icon: typeof FileText;
}[] = [
  { value: "summary", label: "摘要", icon: FileText },
  { value: "key_information", label: "关键信息", icon: KeyRound },
  { value: "timeline", label: "时间线", icon: CalendarRange },
  { value: "entity_recognition", label: "实体识别", icon: ScanSearch },
  { value: "qa", label: "问答", icon: MessageCircleQuestion },
  { value: "relation_mapping", label: "关系映射", icon: Network },
  { value: "tasks", label: "任务", icon: ListTodo },
  { value: "concepts", label: "概念", icon: Lightbulb },
  { value: "custom", label: "自定义", icon: Settings2 },
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

/** 证据引用条目（与 analysis/schemas.py Evidence 逐字段对齐）。 */
export interface EvidenceItem {
  chunk_id: string;
  quote: string;
  confidence?: number;
}

/** 摘要报告 payload（聚合形态：置信与证据在顶层）。 */
export interface SummaryPayload {
  summary: string;
  key_points: string[];
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 关键信息条目（条目形态：置信与证据在条目上）。 */
export interface KeyInfoItemPayload {
  label: string;
  value: string;
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 关键信息报告 payload。 */
export interface KeyInfoPayload {
  items: KeyInfoItemPayload[];
}

/** 时间线条目（与 TimelineEvent 对齐；relative 时 date_normalized 缺省）。 */
export interface TimelineEventPayload {
  date_raw: string;
  date_normalized?: string | null;
  granularity: "exact" | "approximate" | "relative";
  description?: string;
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 时间线报告 payload。 */
export interface TimelinePayload {
  items: TimelineEventPayload[];
}

/** 实体识别条目。 */
export interface RecognizedEntityPayload {
  name: string;
  type?: string;
  description?: string;
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 实体识别报告 payload。 */
export interface EntityRecognitionPayload {
  items: RecognizedEntityPayload[];
}

/** 问答报告 payload（聚合形态；citations 为引用的材料块 ID 列表）。 */
export interface QAPayload {
  question: string;
  answer: string;
  citations?: string[];
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 关系映射条目（头 / 尾 / 类型 / 描述，与 RelationItem 对齐）。 */
export interface RelationItemPayload {
  head: string;
  tail: string;
  type: string;
  description?: string;
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 关系映射报告 payload。 */
export interface RelationMappingPayload {
  items: RelationItemPayload[];
}

/** 任务（行动项）条目（与 ActionItem 对齐；责任方 / 期限为源文原始表述，可缺失）。 */
export interface ActionItemPayload {
  action: string;
  owner_raw?: string;
  deadline_raw?: string;
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 任务报告 payload。 */
export interface TasksPayload {
  items: ActionItemPayload[];
}

/** 概念条目（与 ConceptItem 对齐）。 */
export interface ConceptItemPayload {
  name: string;
  definition?: string;
  related?: string[];
  confidence?: number;
  evidence?: EvidenceItem[];
}

/** 概念报告 payload。 */
export interface ConceptPayload {
  items: ConceptItemPayload[];
}

/** 自定义报告 payload（聚合形态：置信与证据在顶层；fields 为用户 schema 驱动的开放字典）。 */
export interface CustomPayload {
  fields: Record<string, unknown>;
  confidence?: number;
  evidence?: EvidenceItem[];
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
// ---- P7 Agent 模式（T15，与后端 api/schemas.py 对齐）----
export type AgentMode = "react" | "plan_execute"; // rewoo 预留不渲染

export interface AgentSessionOut {
  id: string;
  mode: AgentMode;
  label: string;
  access_level: string;
  library_scope: string;
  created_at: string;
}

export interface AgentSessionListOut {
  items: AgentSessionOut[];
  total: number;
}

export interface AgentMessageOut {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  run_id: string | null;
  created_at: string;
}

export interface AgentRunOut {
  id: string;
  session_id: string;
  status: string;
  steps: number;
  usage: Record<string, number>;
  tool_trace: Array<{
    call: { id: string; name: string; arguments: Record<string, unknown> };
    result: { ok: boolean; output: string; error: string | null };
  }>;
  error: string | null;
  created_at: string;
}

export interface AgentRunRequest {
  question: string;
}

export interface AgentRunAccepted {
  job_id: string;
  status: string;
}
