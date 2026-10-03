const state = { mode: "COMMITTEE", committeeSession: null, candidateToken: null };
export function getState() { return { ...state }; }
export function setState(changes) { Object.assign(state, changes); }
export function clearSensitiveState() { state.committeeSession = null; state.candidateToken = null; }
