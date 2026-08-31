import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api", () => apiMocks);

import { AcademyAttackStoryTimeline } from "@/components/academy/attack-story-timeline";
import { AcademyKnowledgeReview } from "@/components/academy/knowledge-review";
import { AcademyMicroCourses } from "@/components/academy/micro-courses";
import { AcademyScenarioComparison } from "@/components/academy/scenario-comparison";
import { AcademyWhaleTutor } from "@/components/academy/whale-tutor";
import type { AcademyAttackStory, AcademyComparison, AcademyScenario } from "@/lib/types";

const scenario = {
  id: "B01",
  title: "Prompt Breaker",
  risk_family: "Prompt Injection",
  lesson: {
    goal: "区分可信指令与不可信内容",
    why_it_matters: "不可信内容可能越过指令边界。",
    real_world_example: "网页文本影响了 Agent。",
    learning_cycle: ["learn", "guess", "do", "see", "fix", "retest", "summary"],
  },
  expected_evidence: {
    event_types: ["academy.input.received", "academy.guard.blocked"],
    rubric: "选择从输入到阻断点的连续事件",
  },
  hardened_config: { instruction_isolation: true, tool_allowlist: true },
  skills: ["trust-boundary", "evidence-reading"],
} as unknown as AcademyScenario;

const story: AcademyAttackStory = {
  session_id: "session-1",
  scenario_id: "B01",
  mode: "vulnerable",
  outcome: "vulnerability_triggered",
  headline: "不可信内容改变了 Agent 决策",
  explanation: "输入越过信任边界并触发了工具调用。",
  timeline: [{
    sequence: 1,
    event_id: "event-1",
    event_type: "academy.input.received",
    component: "Input",
    source: "User",
    target: "Agent",
    title: "收到本地测试输入",
    explanation: "服务器记录了输入事件。",
    status: "violation",
    risk: "high",
  }],
  technical_details: { event_count: 1 },
};

const comparison: AcademyComparison = {
  scenario_id: "B01",
  ready: true,
  vulnerable: {
    session_id: "session-1",
    mode: "vulnerable",
    result: "漏洞已复现",
    input: { payload: "WHALE_LAB_FAKE_INPUT", payload_sha256: "abc" },
    model_decision: ["接受不可信指令"],
    tool_call: ["调用模拟工具"],
    policy_decision: ["未阻断"],
    output: ["返回虚构数据"],
    evidence: { created: true, id: "evidence-1" },
    finding: { created: true, id: "finding-1", title: "Prompt Injection", severity: "high", status: "open" },
  },
  hardened: {
    session_id: "session-2",
    mode: "hardened",
    result: "防护已验证",
    input: { payload: "WHALE_LAB_FAKE_INPUT", payload_sha256: "abc" },
    model_decision: ["识别不可信指令"],
    tool_call: [],
    policy_decision: ["策略阻断"],
    output: ["安全拒绝"],
    evidence: { created: false },
    finding: { created: false },
  },
  control_changes: [{
    control: "instruction_isolation",
    vulnerable: false,
    hardened: true,
    explanation: "不可信内容被隔离，不能覆盖系统目标。",
  }],
  conclusion: "Hardened 在工具调用前切断了攻击链。",
};

describe("Academy beginner learning loop", () => {
  beforeEach(() => {
    apiMocks.apiRequest.mockReset().mockResolvedValue({
      project_id: "project-1",
      scenario_id: "B01",
      intent: "why_hardened",
      answer: "后端导师：Hardened 在工具调用前切断了攻击链。",
      key_points: ["先经过策略检查", "保留阻断证据"],
      suggested_next_step: "运行相同输入的修复版",
      used_ai: false,
      fallback_reason: "no_model",
      session_context_used: true,
      model_channel_id: null,
      safety_boundary: "defensive_explanation_only",
    });
  });

  it("让零基础微课程可以作答并得到解释", async () => {
    const user = userEvent.setup();
    render(<AcademyMicroCourses courses={[{
      id: "M00",
      order: 0,
      title: "什么是信任边界",
      minutes: 3,
      concepts: ["trust boundary"],
      plain_explanation: "边界决定哪些输入能影响安全决策。",
      analogy: "像门禁一样先验身份。",
      diagram: { nodes: ["外部输入", "策略", "工具"], direction: "LR" },
      interactive_example: {
        prompt: "哪个步骤应该先做？",
        choices: ["直接执行", "先检查策略"],
        answer_index: 1,
        explanation: "应先经过策略检查。",
      },
    }]} />);

    await user.click(screen.getByText("什么是信任边界"));
    await user.click(screen.getByRole("button", { name: "先检查策略" }));
    expect(screen.getByRole("status")).toHaveTextContent("答对了");
    expect(screen.getByRole("status")).toHaveTextContent("应先经过策略检查");
  });

  it("显示真实 Attack Story 与 Vulnerable/Hardened 对照", () => {
    const { rerender } = render(<AcademyAttackStoryTimeline story={story} />);
    expect(screen.getByTestId("academy-attack-story")).toHaveTextContent("不可信内容改变了 Agent 决策");
    expect(screen.getByText("收到本地测试输入")).toBeInTheDocument();

    rerender(<AcademyScenarioComparison comparison={comparison} />);
    expect(screen.getByTestId("academy-vulnerable-hardened-comparison")).toHaveTextContent("Vulnerable 漏洞版");
    expect(screen.getByTestId("academy-vulnerable-hardened-comparison")).toHaveTextContent("Hardened 修复版");
    expect(screen.getByText("Hardened 在工具调用前切断了攻击链。")).toBeInTheDocument();
  });

  it("鲸鱼导师只回答当前课程与防御问题", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AcademyWhaleTutor scenario={scenario} story={story} comparison={comparison} projectId="project-1" sessionId="session-2" />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("academy-whale-tutor")).toHaveTextContent("失败时自动回到本地解释");
    await user.click(screen.getByRole("button", { name: "为什么修复版能拦住？" }));
    expect(await screen.findByText("后端导师：Hardened 在工具调用前切断了攻击链。")).toBeInTheDocument();
    expect(apiMocks.apiRequest).toHaveBeenCalledWith("/academy/scenarios/B01/tutor", {
      method: "POST",
      body: { project_id: "project-1", intent: "why_hardened", session_id: "session-2" },
    });
    expect(screen.getByTestId("academy-whale-tutor")).toHaveTextContent("确定性解释 · no_model");
  });

  it("完成三题知识回顾并允许重新作答", async () => {
    const user = userEvent.setup();
    render(<AcademyKnowledgeReview scenario={scenario} />);

    await user.click(screen.getByRole("button", { name: "服务器保存的连续事件链" }));
    await user.click(screen.getByRole("button", { name: "在危险动作产生副作用前阻断并留下证据" }));
    await user.click(screen.getByRole("button", { name: "本地虚构数据" }));
    expect(screen.getByTestId("academy-knowledge-review")).toHaveTextContent("3/3");
    expect(screen.getByText("全部答对，可以继续下一关。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新回顾" }));
    expect(screen.getByTestId("academy-knowledge-review")).toHaveTextContent("0/3");
  });
});
