// The shared assistant chat body: message list + composer + confirm-gated
// actions. Used by both the slide-over panel and the full Assistant tab; the
// conversation lives in the UI store so the two surfaces stay in sync. It fills
// its parent (parent controls the height and the surrounding chrome).

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Mic, Send, Square } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAiStatus } from "../api/hooks";
import { useUi } from "../store/ui";
import type { ChatMessage, ProposedAction } from "../api/types";
import { Button } from "./ui";
import { startOfZonedDay, zonedDateStr } from "../lib/tz";
import { useVoiceInput } from "../lib/voice";

const SUGGESTIONS = [
  "Summarize my day",
  "What should I work on next?",
  "Did I stick to my plan today?",
  "Draft my standup",
];

function localDate(): string {
  return zonedDateStr();
}

function dayBounds(): { day_start: string; day_end: string } {
  return {
    day_start: new Date(startOfZonedDay()).toISOString(),
    day_end: new Date().toISOString(),
  };
}

export function AssistantChat({ autoFocus = false }: { autoFocus?: boolean }) {
  const { assistantMessages: messages, setAssistantMessages, setCurrentSession, setScreen } =
    useUi();
  const aiStatus = useAiStatus();
  const qc = useQueryClient();

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [actingIdx, setActingIdx] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Speak instead of typing: the transcript is sent like a typed message.
  const voice = useVoiceInput((text) => send(text));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    const history: ChatMessage[] = messages
      .filter((m) => !m.system)
      .map((m) => ({ role: m.role, content: m.content }));
    setAssistantMessages((m) => [...m, { role: "user", content: trimmed }]);
    setInput("");
    setSending(true);
    try {
      const bounds = dayBounds();
      const res = await api.assistantChat({
        messages: [...history, { role: "user", content: trimmed }],
        day_start: bounds.day_start,
        day_end: bounds.day_end,
        local_date: localDate(),
      });
      setAssistantMessages((m) => [
        ...m,
        { role: "assistant", content: res.reply, action: res.action, usedAi: res.used_ai },
      ]);
    } catch {
      setAssistantMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: "Something went wrong reaching the assistant. Please try again.",
          usedAi: false,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function runAction(action: ProposedAction, idx: number) {
    setActingIdx(idx);
    try {
      // Execution is centralized on the backend so the web and desktop clients
      // stay in sync and name->id resolution happens where the Jira client is.
      const res = await api.assistantAct({
        type: action.type,
        args: action.args,
        local_date: localDate(),
      });
      if (res.ok) {
        qc.invalidateQueries();
        if (action.type === "start_session" && res.session_id) {
          setCurrentSession(res.session_id);
          setScreen("active");
        }
        setAssistantMessages((m) =>
          m
            .map((msg, i) => (i === idx ? { ...msg, action: null } : msg))
            .concat([{ role: "assistant", content: `Done. ${res.message}`, system: true }]),
        );
      } else {
        setAssistantMessages((m) => [
          ...m,
          {
            role: "assistant",
            content: res.message || "Could not complete that.",
            system: true,
            usedAi: false,
          },
        ]);
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : "action failed";
      setAssistantMessages((m) => [
        ...m,
        { role: "assistant", content: `Could not complete that: ${detail}`, system: true, usedAi: false },
      ]);
    } finally {
      setActingIdx(null);
    }
  }

  function dismissAction(idx: number) {
    setAssistantMessages((m) => m.map((msg, i) => (i === idx ? { ...msg, action: null } : msg)));
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Ask about your day, or tell me to do something. I can see your active
              session, today's tracked time, your plan, and your tickets.
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-2.5 py-1.5 text-xs text-violet-600 transition-colors hover:border-violet-500/40 hover:bg-violet-500/10 dark:text-violet-300"
                >
                  {s}
                </button>
              ))}
            </div>
            {aiStatus.data && !aiStatus.data.available && (
              <p className="text-xs text-amber-500">
                AI provider not ready. Connect Groq (free) or Ollama in Settings to
                enable the assistant.
              </p>
            )}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] rounded-lg px-3.5 py-2 text-sm ${
                m.role === "user"
                  ? "bg-violet-600 text-white"
                  : m.system
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                    : "bg-slate-100 text-slate-800 dark:bg-white/5 dark:text-slate-100"
              }`}
            >
              <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
              {m.usedAi === false && !m.system && (
                <div className="mt-1 text-[10px] opacity-60">AI unavailable</div>
              )}
              {m.action && (
                <div className="mt-2 rounded-lg border border-violet-500/30 bg-white/70 p-2.5 dark:bg-black/20">
                  <div className="text-xs font-medium text-slate-700 dark:text-slate-200">
                    {m.action.summary}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <Button
                      className="px-3 py-1.5 text-xs"
                      loading={actingIdx === i}
                      onClick={() => runAction(m.action as ProposedAction, i)}
                    >
                      <Check className="h-3.5 w-3.5" />
                      Confirm
                    </Button>
                    <Button
                      variant="ghost"
                      className="px-3 py-1.5 text-xs"
                      onClick={() => dismissAction(i)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="rounded-lg bg-slate-100 px-3.5 py-2 dark:bg-white/5">
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
            </div>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="border-t border-slate-200 p-3 dark:border-white/10"
      >
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder="Ask your assistant..."
            className="max-h-32 min-h-[40px] w-full resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none transition placeholder:text-slate-400 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/15 dark:border-white/10 dark:bg-slate-950/40 dark:text-slate-100 dark:placeholder:text-slate-500"
          />
          {voice.supported && (
            <Button
              type="button"
              variant={voice.recording ? "danger" : "secondary"}
              onClick={voice.toggle}
              loading={voice.busy}
              disabled={sending}
              title={voice.recording ? "Stop and send" : "Speak"}
              className="px-3 py-2.5"
            >
              {voice.recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </Button>
          )}
          <Button type="submit" disabled={!input.trim() || sending} className="px-3 py-2.5">
            <Send className="h-4 w-4" />
          </Button>
        </div>
        {(voice.recording || voice.error) && (
          <p className={`mt-1.5 text-xs ${voice.error ? "text-rose-500" : "text-slate-400"}`}>
            {voice.error ?? "Listening... press stop to send."}
          </p>
        )}
      </form>
    </div>
  );
}
