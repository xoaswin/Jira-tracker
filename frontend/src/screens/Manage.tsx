// Manage screen: open one or more tickets by key and manage each independently
// (edit dates, drive its workflow, complete subtasks). Each opened ticket is a
// collapsible card so several can be worked at once on the narrow layout.

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Search,
  X,
} from "lucide-react";
import { useAuthStatus, useManageView } from "../api/hooks";
import { ApiError } from "../api/client";
import { useUi } from "../store/ui";
import { Banner, Button, Card, Label, Spinner, TextInput } from "../components/ui";
import { ManagePanel, categoryTone } from "../components/ManagePanel";

export function Manage() {
  const auth = useAuthStatus();
  const { manageOpenKey, setManageOpenKey } = useUi();
  const [keyInput, setKeyInput] = useState("");
  // Newest-opened first, so the ticket you just added is at the top.
  const [openKeys, setOpenKeys] = useState<string[]>([]);

  // Deep link from My Tickets: open the requested ticket on mount, then clear
  // the request so it doesn't reopen after the user closes the card.
  useEffect(() => {
    if (manageOpenKey) {
      const k = manageOpenKey.toUpperCase();
      setOpenKeys((keys) => (keys.includes(k) ? keys : [k, ...keys]));
      setManageOpenKey(null);
    }
  }, [manageOpenKey, setManageOpenKey]);

  function open() {
    const k = keyInput.trim().toUpperCase();
    if (!k) return;
    setOpenKeys((keys) => (keys.includes(k) ? keys : [k, ...keys]));
    setKeyInput("");
  }

  function close(key: string) {
    setOpenKeys((keys) => keys.filter((k) => k !== key));
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Manage tickets</h1>
        <p className="mt-1 text-sm text-slate-500">
          Open any tickets by key and manage them side by side: edit dates, move
          them through the workflow, and complete subtasks.
        </p>
      </div>

      <Card className="space-y-3">
        <Label>Ticket key</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <TextInput
              className="pl-9"
              placeholder="e.g. PPVM-431"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && open()}
            />
          </div>
          <Button onClick={open} disabled={!keyInput.trim()}>
            Open
          </Button>
        </div>
      </Card>

      {openKeys.length === 0 && (
        <p className="text-center text-sm text-slate-400">
          No tickets open. Search a key above to start managing one.
        </p>
      )}

      {openKeys.map((key) => (
        <ManageCard
          key={key}
          issueKey={key}
          baseUrl={auth.data?.base_url ?? null}
          onClose={() => close(key)}
        />
      ))}
    </div>
  );
}

// One opened ticket: a collapsible card that fetches and manages the ticket.
// The header stays visible when collapsed and shows the current status.
function ManageCard({
  issueKey,
  baseUrl,
  onClose,
}: {
  issueKey: string;
  baseUrl: string | null;
  onClose: () => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const view = useManageView(issueKey);
  const data = view.data;

  const jiraUrl = baseUrl ? `${baseUrl}/browse/${issueKey}` : null;

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
          )}
          <span className="font-mono text-sm font-semibold text-indigo-600 dark:text-indigo-400">
            {issueKey}
          </span>
          {data && (
            <span
              className={`truncate text-xs font-semibold ${categoryTone(data.status_category)}`}
            >
              {data.status ?? "unknown"}
            </span>
          )}
        </button>
        <div className="flex shrink-0 items-center gap-1">
          {jiraUrl && (
            <a
              href={jiraUrl}
              target="_blank"
              rel="noreferrer"
              title="Open in Jira"
              className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-indigo-600 dark:hover:bg-slate-800"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
          <button
            onClick={onClose}
            title="Close"
            className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-rose-500 dark:hover:bg-slate-800"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 pt-4 dark:border-slate-800">
          {view.isLoading && <Spinner />}
          {view.isError && (
            <Banner tone="error">
              {view.error instanceof ApiError
                ? JSON.stringify(view.error.detail)
                : String(view.error)}
            </Banner>
          )}
          {data && <ManagePanel data={data} />}
        </div>
      )}
    </Card>
  );
}
