const state = {
  mode: "COMMITTEE",
  startupToken: null,
  committeeSession: null,
  currentCaseId: null,
  currentSnapshotId: null,
  activeTaskId: null,
  activeQuestionVariant: null,
  activeQuestionAddition: null,
  selectedQuestion: null,
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
  state.activeQuestionVariant = null;
  state.activeQuestionAddition = null;
  state.selectedQuestion = null;
  state.pendingCaseCreation = null;
}
