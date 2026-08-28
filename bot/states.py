"""FSM states.

Redis holds only what is in flight: which problem is on the table and how many
attempts have been spent on it. Everything historical lives in SQLite.
"""

from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    """Where a user is in the loop."""

    choosing_profile = State()
    """Waiting for a grade profile to be picked, before any problem is issued."""

    awaiting_answer = State()
    """A problem is on the table; the attempt counter says which try this is."""
