import { useState } from "react";
import { Database, Download, KeyRound, ShieldCheck } from "lucide-react";
import { useAuthStatus, useConnect, useDisconnect } from "../api/hooks";
import { api, ApiError } from "../api/client";
import { Banner, Button, Card, Label, TextInput } from "../components/ui";
import { AISettings } from "../components/AISettings";

export function Settings() {
  const status = useAuthStatus();
  const connect = useConnect();
  const disconnect = useDisconnect();

  const [baseUrl, setBaseUrl] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");

  const connected = status.data?.connected;

  function onConnect() {
    connect.mutate({ base_url: baseUrl, email, token });
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect the app to your Jira Cloud site.
        </p>
      </div>

      {connected ? (
        <Card className="space-y-4">
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-6 w-6 text-emerald-500" />
            <div>
              <p className="font-medium">
                Connected as {status.data?.display_name}
              </p>
              <p className="text-sm text-slate-500">
                {status.data?.email} on {status.data?.base_url}
              </p>
            </div>
          </div>
          <p className="text-xs text-slate-400">
            Token stored via the {status.data?.secret_backend} backend, never in
            the database or project files.
          </p>
          <Button
            variant="danger"
            loading={disconnect.isPending}
            onClick={() => disconnect.mutate()}
          >
            Disconnect
          </Button>
        </Card>
      ) : null}

      {/* AI + behaviour settings, available once connected (Phase 5). */}
      {connected && <AISettings />}

      {/* Data: backup + timesheet export. */}
      {connected && <DataSection />}

      {!connected && (
        <Card className="space-y-4">
          <div>
            <Label>Jira base URL</Label>
            <TextInput
              placeholder="https://yourcompany.atlassian.net"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
          <div>
            <Label>Email</Label>
            <TextInput
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <Label>API token</Label>
            <TextInput
              type="password"
              placeholder="Your Jira API token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <p className="mt-1 text-xs text-slate-400">
              Create one at id.atlassian.com under Security, API tokens. It is
              stored in your OS keychain.
            </p>
          </div>

          {connect.isError && (
            <Banner tone="error">
              Could not connect:{" "}
              {connect.error instanceof ApiError
                ? JSON.stringify(connect.error.detail)
                : String(connect.error)}
            </Banner>
          )}

          <Button
            onClick={onConnect}
            loading={connect.isPending}
            disabled={!baseUrl || !email || !token}
          >
            <KeyRound className="h-4 w-4" />
            Connect
          </Button>
        </Card>
      )}
    </div>
  );
}

// Data export: backup the local SQLite (the source of truth for in-flight work)
// and export a timesheet CSV for a range. Both are plain GET downloads, so we
// use anchor navigation rather than fetch.
function DataSection() {
  const [preset, setPreset] = useState("week");
  return (
    <Card className="space-y-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
        <Database className="h-4 w-4 text-indigo-500" />
        Data
      </h2>

      <div>
        <a href={api.backupUrl()} download>
          <Button variant="secondary">
            <Download className="h-4 w-4" />
            Download backup (.db)
          </Button>
        </a>
        <p className="mt-1 text-xs text-slate-400">
          A copy of the local database, your source of truth for in-flight work.
        </p>
      </div>

      <div>
        <Label>Timesheet CSV</Label>
        <div className="flex items-center gap-2">
          <select
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
          >
            <option value="week">This week</option>
            <option value="last_week">Last week</option>
            <option value="month">This month</option>
            <option value="30d">Last 30 days</option>
          </select>
          <a href={api.timesheetCsvUrl(preset)} download>
            <Button variant="secondary">
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
          </a>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Completed sessions in the range, one row each (date, ticket, hours).
        </p>
      </div>
    </Card>
  );
}
