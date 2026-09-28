// Full-page AI Assistant tab. Shares its conversation with the quick slide-over
// panel (both render AssistantChat, backed by the same store state), so the two
// are one continuous, contextual chat.

import { Sparkles, Trash2 } from "lucide-react";
import { AssistantChat } from "../components/AssistantChat";
import { Button, Card } from "../components/ui";
import { useUi } from "../store/ui";

export function Assistant() {
  const { setAssistantMessages } = useUi();

  return (
    <div className="mx-auto flex h-[72vh] min-h-[420px] max-w-3xl flex-col">
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow-md shadow-indigo-900/30 ring-1 ring-inset ring-white/20">
              <Sparkles className="h-4 w-4" />
            </span>
            AI Assistant
          </h1>
          <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">
            Ask about your day, plan, and tickets, or tell me to do something. It is
            grounded in your live data.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setAssistantMessages([])}>
          <Trash2 className="h-4 w-4" />
          New chat
        </Button>
      </div>

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
        <AssistantChat autoFocus />
      </Card>
    </div>
  );
}
