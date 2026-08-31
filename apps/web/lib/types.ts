export type ApiRecord = {
  id: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type ApiPage<T extends ApiRecord = ApiRecord> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type ExperienceMode = "beginner" | "advanced";
export type OnboardingGoal = "learn" | "scan" | "both";

export type UserPreferences = {
  experience_mode: ExperienceMode;
  onboarding_complete: boolean;
  onboarding_goal: OnboardingGoal | null;
};

export type UserPreferencesUpdate = Partial<UserPreferences>;

export type SystemServiceStatus = {
  status: "normal" | "not_started" | "optional" | "abnormal";
  label: string;
  detail: string;
  optional: boolean;
};

export type SystemStatus = {
  overall: "ready" | "degraded";
  checked_at: string;
  services: Record<string, SystemServiceStatus>;
  model_provider_name: string | null;
};

export type Project = ApiRecord & {
  name: string;
  description?: string;
  status?: string;
  finding_count?: number;
  security_score?: number;
};

export type ModelChannel = ApiRecord & {
  project_id?: string | null;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  enabled: boolean;
  api_key_masked?: string | null;
  status?: string;
  last_tested_at?: string;
  timeout?: number;
  max_tokens?: number;
  temperature?: number;
};

export type WebsiteScanCheck = {
  id?: string;
  name: string;
  status: "passed" | "warning" | "failed" | "info" | string;
  severity?: "info" | "low" | "medium" | "high" | "critical" | string;
  explanation?: string;
  message?: string;
  remediation?: string;
};

export type WebsiteScanAiAnalysis = {
  status?: "used" | "degraded" | "not_used" | "not_requested" | string;
  model?: string;
  summary?: string;
  error?: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  priorities?: string[];
  limitations?: string;
  failure_reason?: string;
};

export type WebsiteScan = ApiRecord & {
  project_id: string;
  target_url: string;
  status: string;
  security_score?: number;
  score?: number;
  score_explanation?: string | string[];
  checks?: WebsiteScanCheck[];
  finding_count?: number;
  finding_ids?: string[];
  findings?: unknown[];
  evidence_id?: string | null;
  report_id?: string | null;
  model_channel_id?: string | null;
  ai_analysis?: WebsiteScanAiAnalysis | null;
  ai_status?: "used" | "degraded" | "not_used" | "not_requested" | string;
  ai_used?: boolean;
  ai_degraded?: boolean;
  ai_summary?: string;
  latency_ms?: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_summary?: string | null;
};

export type AuthorizationScope = ApiRecord & {
  project_id: string;
  name: string;
  target_value: string;
  target_type: string;
  status?: string;
  is_authorized: boolean;
  expires_at?: string;
};

export type TestRun = ApiRecord & {
  project_id: string;
  name?: string;
  status: string;
  progress?: number;
  project_name?: string;
  security_score?: number;
  pause_requested?: boolean;
  evaluation_mode?: "rules" | "rules_with_llm_judge";
  judge_model_channel_id?: string | null;
};

export type Finding = ApiRecord & {
  title: string;
  category: string;
  severity: string;
  confidence?: string | number;
  affected_target?: string;
  status: string;
  remediation?: string;
};

export type Report = ApiRecord & {
  name: string;
  formats?: string[];
  status?: string;
  project_name?: string;
  generated_at?: string;
};

export type AcademyProgress = {
  exploit_complete: boolean;
  evidence_complete: boolean;
  mitigation_complete: boolean;
  hardened_complete: boolean;
  completed: boolean;
  hints_used: number[];
  score: number;
  max_score: number;
  last_session_id?: string | null;
  best_session_id?: string | null;
};

export type AcademySummary = {
  name: string;
  version: string;
  scenario_count: number;
  completed_count: number;
  total_score: number;
  max_score: number;
  starter_path: string[];
  learning_path?: string[];
  next_lesson?: AcademyNextLesson | null;
  event_types: string[];
  frameworks: string[];
  isolation: {
    targets: string;
    public_listener: boolean;
    public_egress: boolean;
    data: string;
    success_evaluator: string;
  };
  progress: Record<string, AcademyProgress>;
};

export type AcademyScenarioListItem = {
  id: string;
  title: string;
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  difficulty_stars: number;
  estimated_time: number;
  story: string;
  knowledge_tags: string[];
  owasp_llm: string[];
  owasp_agentic: string[];
  skills?: string[];
  layer?: string[];
  prerequisites?: string[];
  risk_family?: string;
  standards?: AcademyStandardsMapping;
  progress: AcademyProgress;
  starter_path_index?: number | null;
};

export type AcademyEvent = {
  id: string;
  sequence: number;
  timestamp: string;
  event_type: string;
  source: string;
  target: string;
  summary: string;
  status: string;
  risk: string;
  details: Record<string, unknown>;
};

export type AcademySession = ApiRecord & {
  project_id: string;
  user_id: string;
  scenario_id: string;
  mode: "vulnerable" | "hardened";
  payload_sha256: string;
  status: string;
  attack_detected: boolean;
  exploit_success: boolean;
  defense_success: boolean;
  score_awarded: number;
  events: AcademyEvent[];
  canary_flows: Array<Record<string, unknown>>;
  replay_of_id?: string | null;
  finding_id?: string | null;
  evidence_id?: string | null;
  completed_at?: string | null;
};

export type AcademyHint = {
  level: number;
  kind?: "idea" | "location" | "near_solution";
  cost: number;
  unlocked: boolean;
  text?: string | null;
};

export type AcademyMitigation = {
  id: string;
  label: string;
};

export type AcademyScenario = AcademyScenarioListItem & {
  learning_objectives: string[];
  scope: { allowed: string[]; forbidden: string[]; network_requests: string };
  attack_surface: string[];
  architecture: { nodes: string[]; edges: string[][] };
  start_state: {
    mode: string;
    starter_prompt: string;
    fake_data_seeded: boolean;
    walkthrough_hidden: boolean;
  };
  success_conditions: Record<string, unknown>;
  failure_conditions: string[];
  hints: AcademyHint[];
  expected_evidence: { event_types: string[]; rubric: string };
  mitre_atlas: string[];
  cwe: string[];
  mcp_spec: { version: string; concepts: string[] };
  vulnerable_config: Record<string, unknown>;
  hardened_config: Record<string, unknown>;
  detection_notes: string[];
  mitigations: AcademyMitigation[];
  walkthrough: { locked: boolean; cost: number; payloads?: string[]; steps?: string[]; retest?: string };
  framework_references: Record<string, string>;
  risk_family: string;
  standards: AcademyStandardsMapping;
  skills: string[];
  layer: string[];
  prerequisites: string[];
  lesson: {
    goal: string;
    why_it_matters: string;
    real_world_example: string;
    learning_cycle: Array<"learn" | "guess" | "do" | "see" | "fix" | "retest" | "summary">;
  };
};

export type AcademyNextLesson = {
  scenario_id: string;
  title: string;
  action: "start" | "continue";
  reason: string;
};

export type AcademyStandardsMapping = {
  scenario_id: string;
  risk_family: string;
  owasp_llm: string[];
  owasp_agentic: string[];
  mitre_atlas: string[];
  cwe: string[];
  framework_references: Record<string, string>;
};

export type AcademyMicroCourse = {
  id: string;
  order: number;
  title: string;
  minutes: number;
  concepts: string[];
  plain_explanation: string;
  analogy: string;
  diagram: { nodes: string[]; direction: string };
  interactive_example: {
    prompt: string;
    choices: string[];
    answer_index: number;
    explanation: string;
  };
};

export type AcademyMicroCourseList = {
  items: AcademyMicroCourse[];
  total: number;
  total_minutes: number;
};

export type AcademyRoadmapLesson = {
  scenario_id: string;
  title: string;
  difficulty: "Beginner" | "Intermediate" | "Advanced";
  estimated_time: number;
  skills: string[];
  layer: string[];
  prerequisites: string[];
  standards: AcademyStandardsMapping;
  status: "available" | "in_progress" | "completed" | "recommended_later";
  progress: AcademyProgress;
};

export type AcademyRoadmap = {
  project_id: string;
  items: AcademyRoadmapLesson[];
  levels: Record<string, { completed: number; total: number }>;
  completed_count: number;
  total_count: number;
  current_lesson?: AcademyNextLesson | null;
  next_lesson?: AcademyNextLesson | null;
};

export type AcademySkillProgressItem = {
  skill_id: string;
  name: string;
  description: string;
  status: "not_started" | "introduced" | "practicing" | "foundation";
  status_label: "未接触" | "入门" | "练习中" | "掌握基础";
  scenario_ids: string[];
  touched_count: number;
  completed_count: number;
  total_count: number;
  progress_percent: number;
};

export type AcademySkillProgress = {
  project_id: string;
  items: AcademySkillProgressItem[];
  status_order: string[];
};

export type AcademyAttackStoryStep = {
  sequence: number;
  event_id: string;
  event_type: string;
  component: string;
  source: string;
  target: string;
  title: string;
  explanation: string;
  status: string;
  risk: string;
};

export type AcademyAttackStory = {
  session_id: string;
  scenario_id: string;
  mode: "vulnerable" | "hardened";
  outcome: "vulnerability_triggered" | "blocked" | "not_triggered";
  headline: string;
  explanation: string;
  timeline: AcademyAttackStoryStep[];
  control_point?: {
    event_id: string;
    event_type: string;
    component: string;
    explanation: string;
  } | null;
  technical_details: Record<string, unknown>;
};

export type AcademyComparisonSide = {
  session_id: string;
  mode: "vulnerable" | "hardened";
  result: string;
  input: { payload: string; payload_sha256: string };
  model_decision: string[];
  tool_call: string[];
  policy_decision: string[];
  output: string[];
  evidence: { created: boolean; id?: string | null; sha256?: string | null };
  finding: {
    created: boolean;
    id?: string | null;
    title?: string | null;
    severity?: string | null;
    status?: string | null;
  };
};

export type AcademyComparison = {
  scenario_id: string;
  ready: boolean;
  missing_mode?: "vulnerable" | "hardened" | null;
  vulnerable?: AcademyComparisonSide | null;
  hardened?: AcademyComparisonSide | null;
  control_changes: Array<{
    control: string;
    vulnerable: unknown;
    hardened: unknown;
    explanation: string;
  }>;
  conclusion: string;
};

export type AcademyTutorIntent = "meaning" | "why_vulnerable" | "why_hardened" | "evidence" | "simplify";

export type AcademyTutorResponse = {
  project_id: string;
  scenario_id: string;
  intent: AcademyTutorIntent;
  answer: string;
  key_points: string[];
  suggested_next_step: string;
  used_ai: boolean;
  fallback_reason: "no_model" | "channel_unavailable" | "provider_error" | "timeout" | "scope_denied" | "transport_error" | "structured_output" | "unsafe_output" | null;
  session_context_used: boolean;
  model_channel_id?: string | null;
  safety_boundary: "defensive_explanation_only";
};
