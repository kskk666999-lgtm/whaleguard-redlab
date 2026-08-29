import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, type Column } from "@/components/data-table";

type Row = { id: string; name: string; status: string };
const rows: Row[] = Array.from({ length: 11 }, (_, index) => ({ id: String(index + 1), name: `项目 ${index + 1}`, status: index % 2 ? "active" : "archived" }));
const columns: Column<Row>[] = [
  { key: "name", header: "名称", searchValue: (row) => row.name, render: (row) => row.name },
  { key: "status", header: "状态", searchValue: (row) => row.status, render: (row) => row.status },
];

describe("DataTable", () => {
  it("支持搜索、过滤与分页", async () => {
    const user = userEvent.setup();
    render(<DataTable data={rows} columns={columns} rowKey={(row) => row.id} pageSize={5} filters={[{ label: "活跃", value: "active", matches: (row) => row.status === "active" }]} />);

    expect(screen.getByText("第 1 / 3 页")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "搜索当前列表…" }), "项目 11");
    expect(screen.getByText("项目 11")).toBeInTheDocument();
    expect(screen.queryByText("项目 10")).not.toBeInTheDocument();

    await user.clear(screen.getByRole("textbox", { name: "搜索当前列表…" }));
    await user.selectOptions(screen.getByRole("combobox"), "active");
    expect(screen.getAllByText("active").length).toBeGreaterThan(0);
    expect(screen.queryByText("archived")).not.toBeInTheDocument();
  });
});
