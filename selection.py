"""The rules for picking an event to inspect. Pure Python: it works on any
dict-like `state` (st.session_state in the app, a plain dict in the tests).

The keys it uses:
  selected_event_id   the event being inspected, or None
  playing             is the match running?
  match_sec           the match clock, in seconds
  last_wall           real time of the last clock update (see app.advance_clock)
"""
import time


def select(state, event_id, allowed):
    """Inspect an event. `allowed` says whether the current view may select it
    (in Keeper's eyes only events the keeper perceived). Selecting pauses the
    match. Returns True if the event was selected."""
    if not allowed:
        return False
    state["selected_event_id"] = event_id
    state["playing"] = False
    return True


def back_to_live(state, finished):
    """Close the inspector and resume the match (unless it is over)."""
    state["selected_event_id"] = None
    if not finished:
        state["playing"] = True
        state["last_wall"] = time.time()


def restart(state):
    """Restart the match from kickoff: the clock goes to zero and nothing is selected."""
    state["selected_event_id"] = None
    state["match_sec"] = 0
    state["playing"] = True
    state["last_wall"] = time.time()


def jump_to(state, seconds, event_id=None, allowed=True, selected_second=None):
    """Move the clock (the scrubber and the moment buttons) and pause. If an
    event is given and allowed, it becomes the selection. Otherwise a selection
    that would now be in the future (`selected_second` is its time) is dropped."""
    state["match_sec"] = seconds
    state["playing"] = False
    state["last_wall"] = time.time()
    if event_id is not None and allowed:
        state["selected_event_id"] = event_id
    elif selected_second is not None and selected_second > seconds:
        state["selected_event_id"] = None
