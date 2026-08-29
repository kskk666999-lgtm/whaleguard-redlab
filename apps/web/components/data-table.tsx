"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Input, Select } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
  searchValue?: (row: T) => string;
};

export type FilterOption<T> = {
  label: string;
  value: string;
  matches: (row: T, value: string) => boolean;
};

export function DataTable<T>({
  data,
  columns,
  rowKey,
  searchPlaceholder = "搜索当前列表…",
  filterLabel = "全部状态",
  filters = [],
  pageSize = 8,
  emptyTitle,
  emptyDescription,
}: {
  data: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  searchPlaceholder?: string;
  filterLabel?: string;
  filters?: FilterOption<T>[];
  pageSize?: number;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("zh-CN");
    return data.filter((row) => {
      const matchesSearch = !needle || columns.some((column) => column.searchValue?.(row).toLocaleLowerCase("zh-CN").includes(needle));
      const option = filters.find((item) => item.value === filter);
      return matchesSearch && (!option || option.matches(row, filter));
    });
  }, [columns, data, filter, filters, search]);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pages);
  const rows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <div>
      <div className="flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label={searchPlaceholder} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={searchPlaceholder} className="h-9 pl-9" />
        </div>
        {filters.length ? (
          <Select aria-label={filterLabel} value={filter} onChange={(event) => { setFilter(event.target.value); setPage(1); }} className="h-9 sm:w-40">
            <option value="">{filterLabel}</option>
            {filters.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </Select>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">{filtered.length} 条记录</span>
      </div>
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-left text-sm">
            <thead><tr className="border-b bg-muted/35">{columns.map((column) => <th key={column.key} className={cn("px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground", column.className)}>{column.header}</th>)}</tr></thead>
            <tbody>{rows.map((row) => <tr key={rowKey(row)} className="border-b transition-colors last:border-0 hover:bg-muted/30">{columns.map((column) => <td key={column.key} className={cn("px-4 py-3 align-middle", column.className)}>{column.render(row)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title={emptyTitle || (data.length ? "没有匹配结果" : "暂无记录")}
          description={emptyDescription || (data.length ? "尝试调整搜索词或过滤条件。" : "完成首次操作后，记录会显示在这里。")}
        />
      )}
      {filtered.length > pageSize ? (
        <div className="flex items-center justify-between border-t px-4 py-3">
          <span className="text-xs text-muted-foreground">第 {safePage} / {pages} 页</span>
          <div className="flex gap-1">
            <Button aria-label="上一页" size="icon" variant="ghost" className="h-8 w-8" disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft className="h-4 w-4" /></Button>
            <Button aria-label="下一页" size="icon" variant="ghost" className="h-8 w-8" disabled={safePage >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))}><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
