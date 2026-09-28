// Small styled primitives shared across screens.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

// B3 "soft tint": tinted fill with colored text, no gradient/shadow.
const variantClasses: Record<Variant, string> = {
  primary:
    "bg-violet-500/15 text-violet-700 ring-1 ring-inset ring-violet-500/25 hover:bg-violet-500/25 dark:text-violet-300 dark:hover:bg-violet-500/25",
  secondary:
    "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:text-slate-100 dark:hover:bg-white/10",
  ghost:
    "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-white/5 dark:hover:text-white",
  danger:
    "bg-rose-500/15 text-rose-700 ring-1 ring-inset ring-rose-500/25 hover:bg-rose-500/25 dark:text-rose-300 dark:hover:bg-rose-500/25",
};

export function Button({
  variant = "primary",
  loading = false,
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  loading?: boolean;
}) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-all duration-150 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100 ${variantClasses[variant]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-slate-200 bg-white p-5 shadow-md shadow-slate-900/5 dark:border-white/10 dark:bg-slate-900 dark:shadow-lg dark:shadow-black/40 ${className}`}
    >
      {children}
    </div>
  );
}

export function Banner({
  tone = "error",
  children,
}: {
  tone?: "error" | "warning" | "info" | "success";
  children: ReactNode;
}) {
  const tones = {
    error:
      "border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200",
    warning:
      "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200",
    info: "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200",
    success:
      "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${tones[tone]}`}>
      {children}
    </div>
  );
}

export function Spinner() {
  return <Loader2 className="h-5 w-5 animate-spin text-violet-400" />;
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <label className="mb-1.5 block text-sm font-medium text-slate-600 dark:text-slate-300">
      {children}
    </label>
  );
}

const fieldClasses =
  "w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/15 dark:border-white/10 dark:bg-slate-950/40 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-violet-400/70 dark:focus:ring-violet-500/20";

export function TextInput({
  className = "",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  // Merge, don't override: a caller-supplied className is appended so it can
  // add to the field styles (e.g. left padding for an icon) without dropping
  // w-full / border / focus ring.
  return <input className={`${fieldClasses} ${className}`} {...props} />;
}

export function TextArea({
  className = "",
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${fieldClasses} resize-y ${className}`} {...props} />;
}
