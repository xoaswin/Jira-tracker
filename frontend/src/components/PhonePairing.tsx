// Pair a phone with the mobile companion: shows a QR code that carries a
// one-time device token, and lists paired phones with a revoke button. The
// phone then talks to the laptop over the local Wi-Fi (see backend app.mobile).

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smartphone, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { MobilePairResult } from "../api/types";
import { formatClock, formatDate } from "../lib/tz";
import { Banner, Button, Card } from "./ui";

const KEY = ["mobile"] as const;

function seen(iso: string | null): string {
  if (!iso) return "never opened";
  return `last seen ${formatDate(iso, { day: "numeric", month: "short" })} ${formatClock(iso)}`;
}

export function PhonePairing() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: api.mobileStatus, refetchInterval: 15_000 });
  const [pairing, setPairing] = useState<MobilePairResult | null>(null);

  const pair = useMutation({
    mutationFn: () => api.pairPhone(),
    onSuccess: (res) => {
      setPairing(res);
      qc.setQueryData(KEY, res);
    },
  });
  const unpair = useMutation({
    mutationFn: (id: number) => api.unpairPhone(id),
    onSuccess: (res) => qc.setQueryData(KEY, res),
  });

  const devices = status.data?.devices ?? [];
  const wslAddress = status.data?.lan_ip?.startsWith("172.");

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <Smartphone className="h-4 w-4" />
          Phone
        </h2>
        {status.data && devices.length > 0 && (
          <span className={`text-xs ${status.data.running ? "text-emerald-500" : "text-slate-400"}`}>
            {status.data.running
              ? `Listening on ${status.data.lan_ip ?? "?"}:${status.data.port}`
              : "Not listening"}
          </span>
        )}
      </div>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Start, pause, stop and switch your timer from your phone on the same Wi-Fi.
        Your Jira token never leaves this laptop.
      </p>

      {pairing ? (
        <div className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/50 p-4 dark:border-violet-900 dark:bg-violet-950/30">
          <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-start">
            <div
              className="shrink-0 overflow-hidden rounded-lg bg-white p-1 [&>svg]:h-44 [&>svg]:w-44"
              // Generated server-side by segno from our own URL; not user input.
              dangerouslySetInnerHTML={{ __html: pairing.qr_svg }}
            />
            <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-600 dark:text-slate-300">
              <li>Connect your phone to the same Wi-Fi as this laptop.</li>
              <li>Scan the code with the phone camera and open the link.</li>
              <li>
                Add it to your home screen: iPhone <b>Share &rarr; Add to Home Screen</b>,
                Android <b>&#8942; &rarr; Add to Home screen</b>.
              </li>
              <li>
                If Windows asks to allow <b>jira-tracker-backend</b> on the network, allow
                <b> Private networks</b>.
              </li>
            </ol>
          </div>
          <p className="break-all text-xs text-slate-400">
            Or open on the phone: {pairing.url.split("#")[0]} (the code carries the pairing key)
          </p>
          {pairing.alternate_urls.length > 0 && (
            <details className="text-xs text-slate-400">
              <summary className="cursor-pointer">Phone can't connect?</summary>
              <p className="mt-1">
                This laptop has other network addresses. Try scanning again after pairing
                with one of these instead:
              </p>
              <ul className="mt-1 space-y-0.5">
                {pairing.alternate_urls.map((u) => (
                  <li key={u} className="break-all font-mono">
                    {u.split("#")[0]}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <Button variant="secondary" onClick={() => setPairing(null)}>
            Done
          </Button>
        </div>
      ) : (
        <Button onClick={() => pair.mutate()} loading={pair.isPending}>
          <Smartphone className="h-4 w-4" />
          {devices.length ? "Pair another phone" : "Pair a phone"}
        </Button>
      )}

      {wslAddress && (
        <Banner tone="warning">
          This looks like the WSL dev backend ({status.data?.lan_ip}), which your phone can't
          reach. Pair from the installed Jira Tracker app instead.
        </Banner>
      )}
      {pair.isError && <Banner tone="error">{String(pair.error)}</Banner>}

      {devices.length > 0 && (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {devices.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="text-sm font-medium">{d.name}</p>
                <p className="truncate text-xs text-slate-400">{seen(d.last_seen_at)}</p>
              </div>
              <Button
                variant="ghost"
                onClick={() => unpair.mutate(d.id)}
                loading={unpair.isPending && unpair.variables === d.id}
                title="Revoke this phone's access"
              >
                <Trash2 className="h-4 w-4" />
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
