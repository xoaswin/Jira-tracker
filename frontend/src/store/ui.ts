// Small amount of local UI state (section 3: Zustand for UI, TanStack Query for
// server state). Remembers the last used board across reloads.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Screen =
  | "start"
  | "match"
  | "active"
  | "finish"
  | "dashboard"
  | "mytickets"
  | "manage"
  | "insights"
  | "settings";

interface UiState {
  screen: Screen;
  selectedBoardId: number | null;
  draftDescription: string;
  currentSessionId: number | null;
  // An issue key detected from the current git branch, carried from Start to
  // Match so it can preselect at full confidence (Phase 3, section 9).
  branchKey: string | null;
  // When true, "Find ticket" searches across all pinned boards instead of just
  // the selected board (multi-board search).
  searchPinned: boolean;
  // The board set Match should search, resolved on the Start screen.
  matchBoardIds: number[];
  // When true, the Match screen auto-opens the create-issue draft (the user
  // chose "Create new ticket" from Start rather than "Find ticket").
  createIntent: boolean;
  // A ticket key to auto-open when the Manage screen mounts, set when deep-
  // linking from My Tickets ("Manage" on an overdue ticket). Cleared once read.
  manageOpenKey: string | null;
  // Hours of capacity to plan against on the Plan My Day view (persisted).
  planCapacityHours: number;
  // Whether the command palette overlay is open (driven by "/" or the header
  // button). In the store so any component can toggle it without window events.
  commandOpen: boolean;

  setScreen: (s: Screen) => void;
  setSelectedBoard: (id: number | null) => void;
  setDraftDescription: (text: string) => void;
  setCurrentSession: (id: number | null) => void;
  setBranchKey: (key: string | null) => void;
  setSearchPinned: (on: boolean) => void;
  setMatchBoardIds: (ids: number[]) => void;
  setCreateIntent: (on: boolean) => void;
  setManageOpenKey: (key: string | null) => void;
  openInManage: (key: string) => void;
  setPlanCapacityHours: (hours: number) => void;
  setCommandOpen: (open: boolean) => void;
  reset: () => void;
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      screen: "start",
      selectedBoardId: null,
      draftDescription: "",
      currentSessionId: null,
      branchKey: null,
      searchPinned: false,
      matchBoardIds: [],
      createIntent: false,
      manageOpenKey: null,
      planCapacityHours: 6,
      commandOpen: false,

      setScreen: (screen) => set({ screen }),
      setSelectedBoard: (selectedBoardId) => set({ selectedBoardId }),
      setDraftDescription: (draftDescription) => set({ draftDescription }),
      setCurrentSession: (currentSessionId) => set({ currentSessionId }),
      setBranchKey: (branchKey) => set({ branchKey }),
      setSearchPinned: (searchPinned) => set({ searchPinned }),
      setMatchBoardIds: (matchBoardIds) => set({ matchBoardIds }),
      setCreateIntent: (createIntent) => set({ createIntent }),
      setManageOpenKey: (manageOpenKey) => set({ manageOpenKey }),
      openInManage: (key) => set({ manageOpenKey: key, screen: "manage" }),
      setPlanCapacityHours: (planCapacityHours) => set({ planCapacityHours }),
      setCommandOpen: (commandOpen) => set({ commandOpen }),
      reset: () =>
        set({
          screen: "start",
          draftDescription: "",
          currentSessionId: null,
          branchKey: null,
          createIntent: false,
        }),
    }),
    {
      name: "jira-tracker-ui",
      // Persist the last board and the search-pinned preference; the rest is
      // transient.
      partialize: (state) => ({
        selectedBoardId: state.selectedBoardId,
        searchPinned: state.searchPinned,
        planCapacityHours: state.planCapacityHours,
      }),
    },
  ),
);
