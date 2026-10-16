import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef } from "react";
import { FIELD_NAMES, type FieldName, type RecordItem } from "../api/client";
import { FIELD_LABELS } from "../lib/fields";
import { ConfidenceBadge, Highlighted, SourceTag } from "./ui";

const WIDTH: Record<string, number> = {
  idx: 56,
  raw: 380,
  province: 150,
  city: 120,
  district: 130,
  living_area: 130,
  street_type: 110,
  street_name: 170,
  house: 70,
  apartment: 60,
  entrance: 70,
  floor: 60,
  landmark: 160,
  confidence: 80,
};

export function RecordsTable({
  items,
  selected,
  onSelect,
  threshold,
}: {
  items: RecordItem[];
  selected: number | null;
  onSelect: (idx: number) => void;
  threshold: number;
}) {
  const columns = useMemo<ColumnDef<RecordItem>[]>(
    () => [
      {
        id: "idx",
        header: "#",
        cell: ({ row }) => (
          <span className="tabular-nums text-slate-400">
            {row.original.reviewed ? <span className="text-brand-600">✓ </span> : null}
            {row.original.idx + 1}
          </span>
        ),
      },
      {
        id: "raw",
        header: "Исходная строка",
        cell: ({ row }) => (
          <Highlighted raw={String(row.original.record.raw_address ?? "")} fields={row.original.fields} />
        ),
      },
      ...FIELD_NAMES.map<ColumnDef<RecordItem>>((f: FieldName) => ({
        id: f,
        header: FIELD_LABELS[f],
        cell: ({ row }) => {
          const v = row.original.record[f];
          return v == null ? (
            <span className="text-slate-300">—</span>
          ) : (
            <span className={row.original.edited.includes(f) ? "font-semibold" : undefined}>
              {v}
              <SourceTag source={row.original.fields[f]?.source} />
            </span>
          );
        },
      })),
      {
        id: "confidence",
        header: "Увер.",
        cell: ({ row }) => <ConfidenceBadge value={row.original.record.confidence} threshold={threshold} />,
      },
    ],
    [threshold],
  );

  const table = useReactTable({ data: items, columns, getCoreRowModel: getCoreRowModel() });
  const rows = table.getRowModel().rows;
  const parent = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parent.current,
    estimateSize: () => 52,
    overscan: 12,
    measureElement: (el) => el.getBoundingClientRect().height,
  });
  const total = Object.values(WIDTH).reduce((a, b) => a + b, 0);

  // выбранная строка всегда в зоне видимости (навигация с клавиатуры)
  useEffect(() => {
    if (selected == null) return;
    const i = items.findIndex((it) => it.idx === selected);
    if (i >= 0) virt.scrollToIndex(i, { align: "auto" });
  }, [selected, items, virt]);

  return (
    <div ref={parent} className="h-full overflow-auto rounded-xl border border-slate-200 bg-white">
      <div style={{ width: total, minWidth: "100%" }}>
        <div className="sticky top-0 z-10 flex border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-600">
          {table.getFlatHeaders().map((h) => (
            <div key={h.id} style={{ width: WIDTH[h.id] }} className="shrink-0 px-2 py-2">
              {flexRender(h.column.columnDef.header, h.getContext())}
            </div>
          ))}
        </div>
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {virt.getVirtualItems().map((v) => {
            const row = rows[v.index];
            if (!row) return null;
            const isSel = row.original.idx === selected;
            return (
              <div
                key={row.id}
                data-index={v.index}
                ref={virt.measureElement}
                onClick={() => onSelect(row.original.idx)}
                onKeyDown={(e) => e.key === "Enter" && onSelect(row.original.idx)}
                tabIndex={-1}
                className={`absolute left-0 flex w-full cursor-pointer border-b border-slate-100 text-sm ${
                  isSel ? "bg-brand-50 ring-1 ring-inset ring-brand-500" : "hover:bg-slate-50"
                }`}
                style={{ transform: `translateY(${v.start}px)` }}
              >
                {row.getVisibleCells().map((c) => (
                  <div
                    key={c.id}
                    style={{ width: WIDTH[c.column.id] }}
                    className="min-w-0 shrink-0 px-2 py-2 break-words"
                  >
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
        {rows.length === 0 && <div className="p-8 text-center text-sm text-slate-500">Ничего не найдено</div>}
      </div>
    </div>
  );
}
