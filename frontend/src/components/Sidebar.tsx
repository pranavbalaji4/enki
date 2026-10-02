"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { api, type NodeOut } from "@/lib/api";
import { useAppState } from "./AppState";

type Draft = { parentId: number | null; kind: "folder" | "session" } | null;

export default function Sidebar() {
  const { nodes, newInsights, backendError, refresh } = useAppState();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [draft, setDraft] = useState<Draft>(null);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const children = useMemo(() => {
    const m = new Map<number | null, NodeOut[]>();
    for (const n of nodes) {
      const list = m.get(n.parent_id ?? null) ?? [];
      list.push(n);
      m.set(n.parent_id ?? null, list);
    }
    for (const list of m.values())
      list.sort((a, b) => (a.kind === b.kind ? a.title.localeCompare(b.title, undefined, { numeric: true }) : a.kind === "folder" ? -1 : 1));
    return m;
  }, [nodes]);

  async function create(title: string) {
    if (!draft || !title.trim()) return setDraft(null);
    const node = await api.createNode({ kind: draft.kind, title, parent_id: draft.parentId });
    if (draft.parentId != null) setOpen((o) => ({ ...o, [draft.parentId!]: true }));
    setDraft(null);
    await refresh();
    router.push(node.kind === "session" ? `/s/${node.id}` : `/n/${node.id}`);
  }

  async function rename(id: number, title: string) {
    setRenaming(null);
    if (title.trim()) {
      await api.renameNode(id, title);
      await refresh();
    }
  }

  async function remove(id: number) {
    setConfirmDelete(null);
    await api.deleteNode(id);
    await refresh();
    router.push("/");
  }

  function href(n: NodeOut) {
    return n.kind === "session" ? `/s/${n.id}` : `/n/${n.id}`;
  }

  function renderLevel(parentId: number | null, depth: number): React.ReactNode {
    const items = children.get(parentId) ?? [];
    return (
      <>
        {items.map((n) => {
          const active = pathname === href(n);
          const isOpen = open[n.id] ?? true;
          return (
            <div key={n.id}>
              <div
                className={`group flex items-center gap-1 rounded-md pr-1 text-[13.5px] ${
                  active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-sunken"
                }`}
                style={{ paddingLeft: 6 + depth * 14 }}
              >
                {n.kind === "folder" ? (
                  <button
                    aria-label={isOpen ? "Collapse" : "Expand"}
                    onClick={() => setOpen((o) => ({ ...o, [n.id]: !isOpen }))}
                    className="w-4 shrink-0 text-ink-faint hover:text-ink"
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                ) : (
                  <span className="w-4 shrink-0 text-center text-ink-faint">
                    {n.status === "reviewed" ? "✦" : n.status === "reviewing" ? "…" : "·"}
                  </span>
                )}
                {renaming === n.id ? (
                  <InlineInput initial={n.title} onDone={(t) => rename(n.id, t)} />
                ) : (
                  <Link
                    href={href(n)}
                    onDoubleClick={() => setRenaming(n.id)}
                    className={`flex-1 truncate py-1.5 ${n.kind === "folder" ? "font-medium text-ink" : ""}`}
                    title={n.title}
                  >
                    {n.title}
                  </Link>
                )}
                {confirmDelete === n.id ? (
                  <span className="flex shrink-0 items-center gap-1 text-xs">
                    <button onClick={() => remove(n.id)} className="rounded px-1.5 py-0.5 text-bad hover:bg-bad-soft">
                      Delete
                    </button>
                    <button onClick={() => setConfirmDelete(null)} className="rounded px-1.5 py-0.5 hover:bg-sunken">
                      Keep
                    </button>
                  </span>
                ) : (
                  <span className="hidden shrink-0 items-center gap-0.5 group-hover:flex group-focus-within:flex">
                    {n.kind === "folder" && (
                      <>
                        <IconBtn label="New chat here" onClick={() => setDraft({ parentId: n.id, kind: "session" })}>＋</IconBtn>
                        <IconBtn label="New folder here" onClick={() => setDraft({ parentId: n.id, kind: "folder" })}>⊞</IconBtn>
                      </>
                    )}
                    <IconBtn label="Rename" onClick={() => setRenaming(n.id)}>✎</IconBtn>
                    <IconBtn label="Delete" onClick={() => setConfirmDelete(n.id)}>×</IconBtn>
                  </span>
                )}
              </div>
              {n.kind === "folder" && isOpen && (
                <>
                  {renderLevel(n.id, depth + 1)}
                  {draft?.parentId === n.id && <DraftRow depth={depth + 1} draft={draft} onDone={create} />}
                </>
              )}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <aside className="flex h-full w-[272px] shrink-0 flex-col border-r border-line bg-panel">
      <div className="px-4 pb-3 pt-5">
        <Link href="/" className="block">
          <div className="font-serif text-2xl font-semibold tracking-tight">Enki</div>
          <div className="text-xs text-ink-faint">learns how you learn</div>
        </Link>
      </div>

      <nav className="space-y-0.5 px-2 text-[13.5px]">
        <NavLink href="/insights" active={pathname === "/insights"}>
          <span>Insights</span>
          {newInsights > 0 && (
            <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-5 text-panel">{newInsights}</span>
          )}
        </NavLink>
        <NavLink href="/n/0" active={pathname === "/n/0"}>
          <span>How I learn (global)</span>
        </NavLink>
      </nav>

      <div className="mt-5 flex items-center justify-between px-4 pb-1">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">Workspace</span>
        <span className="flex gap-0.5">
          <IconBtn label="New top-level folder" onClick={() => setDraft({ parentId: null, kind: "folder" })}>⊞</IconBtn>
          <IconBtn label="New top-level chat" onClick={() => setDraft({ parentId: null, kind: "session" })}>＋</IconBtn>
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-6">
        {renderLevel(null, 0)}
        {draft?.parentId === null && <DraftRow depth={0} draft={draft} onDone={create} />}
        {nodes.length === 0 && !draft && !backendError && (
          <p className="px-3 py-4 text-sm text-ink-faint">
            Start with a folder for a subject — say, “CS” — then add topics and chats inside it.
          </p>
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
      className={`flex items-center justify-between rounded-md px-3 py-1.5 ${active ? "bg-accent-soft text-ink" : "text-ink-soft hover:bg-sunken"}`}
    >
      {children}
    </Link>
  );
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded text-[13px] text-ink-faint hover:bg-sunken hover:text-ink"
    >
      {children}
    </button>
  );
}

function DraftRow({ depth, draft, onDone }: { depth: number; draft: NonNullable<Draft>; onDone: (t: string) => void }) {
  return (
    <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: 6 + depth * 14 }}>
      <span className="w-4 text-center text-ink-faint">{draft.kind === "folder" ? "▸" : "·"}</span>
      <InlineInput initial="" placeholder={draft.kind === "folder" ? "Folder name" : "Chat title, e.g. Lec 7: Heaps"} onDone={onDone} />
    </div>
  );
}

function InlineInput({ initial, placeholder, onDone }: { initial: string; placeholder?: string; onDone: (t: string) => void }) {
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
      value={v}
      placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => finish(v)}
      onKeyDown={(e) => {
        if (e.key === "Enter") finish(v);
        if (e.key === "Escape") finish("");
      }}
      className="min-w-0 flex-1 rounded border border-accent bg-panel px-1.5 py-1 text-[13.5px] outline-none"
    />
  );
}
