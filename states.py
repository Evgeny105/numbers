from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    solved = State()
    await_1_answer = State()
    await_2_answer = State()
    await_3_answer = State()
