const state = {
  mode: "COMMITTEE",
  startupToken: null,
  committeeSession: null,
  candidateToken: null,
  candidateAttemptId: null,
  candidateCaseId: null,
};

export function getState() { return { ...state }; }
export function setState(changes) { Object.assign(state, changes); }
export function clearSensitiveState() {
  state.committeeSession = null;
  state.candidateToken = null;
  state.candidateAttemptId = null;
  state.candidateCaseId = null;
}

export function enterCandidateMode({ candidateToken, attemptId, caseId }) {
  state.mode = "CANDIDATE";
  state.committeeSession = null;
  state.candidateToken = candidateToken;
  state.candidateAttemptId = attemptId;
  state.candidateCaseId = caseId;
}
