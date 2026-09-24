// Native desktop notifications (Web Notification API). Used alongside
// in-app prompts (CheckinPrompt) so a check-in due while the tab is
// unfocused still surfaces as a Windows toast, not just a modal you'd only
// see by switching back to the tab. No-op wherever unsupported or
// unauthorized; the in-app modal is always the fallback.

const SUPPORTED = typeof window !== "undefined" && "Notification" in window;

export function notificationsSupported(): boolean {
  return SUPPORTED;
}

export function notificationPermission(): NotificationPermission | "unsupported" {
  if (!SUPPORTED) return "unsupported";
  return Notification.permission;
}

// Must be called from a user gesture (button click) in most browsers'
// effective policy, even though the spec doesn't strictly require it.
export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!SUPPORTED) return "denied";
  if (Notification.permission !== "default") return Notification.permission;
  return Notification.requestPermission();
}

export type NotifyOutcome = "shown" | "errored" | "not-permitted";

// Reports what actually happened (rather than firing blind) so a caller can
// surface it: the constructor succeeding does NOT mean the OS displayed
// anything (e.g. the browser's app is muted in Windows Settings > System >
// Notifications, or Focus Assist is on) - only the 'show' event confirms
// that.
export function notifyDesktop(
  title: string,
  body: string,
  onClick?: () => void,
  onOutcome?: (outcome: NotifyOutcome, detail?: string) => void,
): void {
  if (!SUPPORTED || Notification.permission !== "granted") {
    onOutcome?.("not-permitted");
    return;
  }
  try {
    const n = new Notification(title, {
      body,
      // A shared tag replaces the previous OS entry instead of stacking one
      // per interval. Combined with requireInteraction, a same-tag
      // notification can silently update the existing (already-dismissed?
      // or unseen) entry in the Action Center WITHOUT re-popping a toast -
      // that's spec-legal browser behaviour, not a bug on our end, but it
      // means back-to-back calls with an unread predecessor can go visually
      // unnoticed. Suffixing the tag with a timestamp forces every call to
      // be a genuinely new entry that always pops.
      tag: `jira-tracker-checkin-${Date.now()}`,
      // Windows auto-dismisses a toast after ~5s by default; this pins it in
      // the Action Center-style tray until you click or dismiss it, so it's
      // still there when you next look at the screen.
      requireInteraction: true,
    });
    n.onshow = () => onOutcome?.("shown");
    n.onerror = () => onOutcome?.("errored");
    n.onclick = () => {
      window.focus();
      onClick?.();
      n.close();
    };
  } catch (err) {
    onOutcome?.("errored", err instanceof Error ? err.message : String(err));
  }
}
