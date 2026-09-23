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

export function notifyDesktop(
  title: string,
  body: string,
  onClick?: () => void,
): void {
  if (!SUPPORTED || Notification.permission !== "granted") return;
  const n = new Notification(title, {
    body,
    // Reuses one OS notification slot instead of stacking a new toast every
    // interval if a previous one went unseen.
    tag: "jira-tracker-checkin",
  });
  n.onclick = () => {
    window.focus();
    onClick?.();
    n.close();
  };
}
