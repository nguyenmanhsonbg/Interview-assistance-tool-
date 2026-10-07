const state = {
  mode: "COMMITTEE",
  startupToken: null,
  committeeSession: null,
  currentCaseId: null,
  currentSnapshotId: null,
  activeTaskId: null,
  pendingCaseCreation: null,
};

export function getState() {
  return { ...state };
}

export function setState(changes) {
  Object.assign(state, changes);
}

export function clearSensitiveState() {
  state.mode = "COMMITTEE";
  state.committeeSession = null;
  state.currentCaseId = null;
  state.currentSnapshotId = null;
  state.activeTaskId = null;
  state.pendingCaseCreation = null;
}
