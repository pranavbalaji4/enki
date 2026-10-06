"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { api, type NodeOut } from "@/lib/api";
import { runIsActive, useAppState } from "./AppState";

export const STAGE_LABEL: Record<string, string> = {
  classify: "Sorting chats",
  topics: "Building your topics",
  turns: "Reading each reply",
  review: "Reviewing chats",
  profile: "Writing your profile",
  done: "Done",
};

export default function Sidebar() {
  const { nodes, run, backendError, refresh } = useAppState();
  const pathname = usePathname();
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [renaming, setRenaming] = useState<number | null>(null);

  const { children, chatCount } = useMemo(() => {
    const children = new Map<number | null, NodeOut[]>();
    const chatCount = new Map<number, number>();
    for (const n of nodes) {
      if (n.kind === "session") {
        if (n.parent_id != null && n.is_learning) chatCount.set(n.parent_id, (chatCount.get(n.parent_id) ?? 0) + 1);
        continue;
      }
      const list = children.get(n.parent_id ?? null) ?? [];
      list.push(n);
      children.set(n.parent_id ?? null, list);
    }
    for (const list of children.values()) list.sort((a, b) => a.title.localeCompare(b.title));
    return { children, chatCount };
  }, [nodes]);

  async function rename(id: number, title: string) {
    setRenaming(null);
    if (title.trim()) {
      await api.renameNode(id, title);
      await refresh();
    }
  }

  function renderLevel(parentId: number | null, depth: number): React.ReactNode {
    return (children.get(parentId) ?? []).map((n) => {
      const kids = children.get(n.id) ?? [];
      const isOpen = open[n.id] ?? true;
      const href = `/topics/${n.id}`;
      const count = depth === 0 ? kids.reduce((s, k) => s + (chatCount.get(k.id) ?? 0), 0) : chatCount.get(n.id) ?? 0;
      return (
        <div key={n.id}>
          <div
            className={`group flex items-center gap-1 rounded-md pr-2 text-sm ${
              pathname === href ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-panel hover:text-ink"
            }`}
            style={{ paddingLeft: 4 + depth * 16 }}
          >
            {kids.length > 0 ? (
              <button
                aria-label={isOpen ? `Collapse ${n.title}` : `Expand ${n.title}`}
                onClick={() => setOpen((o) => ({ ...o, [n.id]: !isOpen }))}
                className="grid h-6 w-5 shrink-0 place-items-center text-ink-faint hover:text-ink"
              >
                <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden className={isOpen ? "rotate-90" : ""}>
                  <path d="M3 1.5 7 5 3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              </button>
            ) : (
              <span className="w-5 shrink-0" />
            )}
            {renaming === n.id ? (
              <InlineInput initial={n.title} onDone={(t) => rename(n.id, t)} />
            ) : (
              <Link
                href={href}
                onDoubleClick={() => setRenaming(n.id)}
                title={`${n.title} (double-click to rename)`}
                className={`flex-1 truncate py-1.5 ${depth === 0 ? "font-medium text-ink" : ""}`}
              >
                {n.title}
              </Link>
            )}
            {count > 0 && renaming !== n.id && <span className="tabular text-xs text-ink-faint">{count}</span>}
          </div>
          {isOpen && renderLevel(n.id, depth + 1)}
        </div>
      );
    });
  }

  const hasTopics = (children.get(null) ?? []).length > 0;

  return (
    <aside className="flex shrink-0 flex-col border-b border-line bg-sunken md:h-full md:w-64 md:border-b-0 md:border-r">
      <div className="flex items-center gap-4 px-5 py-4 md:block md:pb-5 md:pt-7">
        <Link href="/" className="font-serif text-2xl font-semibold tracking-tight text-ink">
          Enki
        </Link>
        <nav className="flex gap-1 text-sm md:mt-6 md:flex-col md:gap-0.5">
          <NavLink href="/" active={pathname === "/"}>
            Insights
          </NavLink>
          <NavLink href="/ask" active={pathname === "/ask"}>
            Ask
          </NavLink>
          <NavLink href="/import" active={pathname === "/import"}>
            Import
          </NavLink>
        </nav>
      </div>

      {runIsActive(run) && run && (
        <Link href="/import" className="mx-3 mb-3 hidden rounded-lg border border-line px-3 py-2.5 md:block hover:border-accent">
          <span className="flex justify-between text-xs text-ink-soft">
            <span>{STAGE_LABEL[run.stage] ?? run.stage}</span>
            {run.stage_total > 0 && (
              <span className="tabular">
                {run.stage_done}/{run.stage_total}
              </span>
            )}
          </span>
          <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-panel">
            <span
              className="block h-full bg-accent transition-[width]"
              style={{ width: `${run.stage_total ? (run.stage_done / run.stage_total) * 100 : 8}%` }}
            />
          </span>
        </Link>
      )}

      <div className="hidden min-h-0 flex-1 overflow-y-auto px-2 pb-6 md:block">
        {hasTopics && <p className="px-3 pb-1 pt-2 text-xs text-ink-faint">Topics</p>}
        {renderLevel(null, 0)}
        {!hasTopics && !backendError && (
          <p className="px-3 py-2 text-sm text-ink-faint">Your topics appear here once your chats are analyzed.</p>
        )}
        {backendError && <p className="m-2 rounded-md bg-bad-soft p-3 text-xs text-bad">{backendError}</p>}
      </div>
    </aside>
  );
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-md px-3 py-1.5 ${active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-panel hover:text-ink"}`}
    >
      {children}
    </Link>
  );
}

function InlineInput({ initial, onDone }: { initial: string; onDone: (t: string) => void }) {
  const [v, setV] = useState(initial);
  const finished = useRef(false);
  const finish = (t: string) => {
    if (finished.current) return; // Enter unmounts the input, which also fires blur
    finished.current = true;
    onDone(t);
  };
  return (
    <input
      autoFocus
      aria-label="Topic name"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => finish(v)}
      onKeyDown={(e) => {
        if (e.key === "Enter") finish(v);
        if (e.key === "Escape") finish("");
      }}
      className="min-w-0 flex-1 rounded border border-accent bg-panel px-1.5 py-1 text-sm outline-none"
    />
  );
}
