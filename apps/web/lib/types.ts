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

export type Project = ApiRecord & {
  name: string;
  description?: string;
  status?: string;
  finding_count?: number;
  security_score?: number;
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
