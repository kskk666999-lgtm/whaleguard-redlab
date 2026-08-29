import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunApprovalControls } from "@/components/run-approval-controls";

const approval = {
  id: "11111111-1111-4111-8111-111111111111",
  project_id: "22222222-2222-4222-8222-222222222222",
  run_id: "33333333-3333-4333-8333-333333333333",
  action_type: "request_sensitive_demo_data",
  risk_level: "high",
  reason: "模拟敏感数据请求必须人工确认",
  status: "pending",
};

describe("RunApprovalControls", () => {
  it("填写理由前禁用决定，填写后提交精确批准合同", async () => {
    const onDecision = vi.fn();
    render(<RunApprovalControls approval={approval} loading={false} busy={false} onRetry={vi.fn()} onDecision={onDecision} />);
    const approve = screen.getByRole("button", { name: /批准并继续/ });
    expect(approve).toBeDisabled();
    await userEvent.type(screen.getByLabelText("审批理由"), "已核验项目 Scope 与操作目的");
    expect(approve).toBeEnabled();
    await userEvent.click(approve);
    expect(onDecision).toHaveBeenCalledWith("approved", "已核验项目 Scope 与操作目的");
  });

  it("显示读取错误并允许真实重试动作", async () => {
    const onRetry = vi.fn();
    render(<RunApprovalControls loading={false} busy={false} error={new Error("403 权限不足")} onRetry={onRetry} onDecision={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("403 权限不足");
    await userEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
