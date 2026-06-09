"""Interactive quiz about Nintendo Switch CFW topics."""
import json
import pathlib
import random
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

quiz_router = Router()

# ── Quiz questions loaded from quiz_data.json ─────────────────────────────────
_QUIZ_DATA_PATH = pathlib.Path(__file__).parent.parent.parent / "quiz_data.json"


def _load_quiz_questions() -> list:
    with open(_QUIZ_DATA_PATH, encoding="utf-8") as _f:
        return json.load(_f)


QUIZ_QUESTIONS = _load_quiz_questions()

# ── Quiz state ─────────────────────────────────────────────────────────────────
# str(user_id) -> {"q_idx": int, "score": int, "total": int,
#                  "msg_id": int, "order": list[int], "ts": float}
QUIZ_STATE: dict = {}

_QUIZ_TTL = 3600  # 1 hour session TTL
_LETTERS = ["A", "B", "C", "D"]


def _cleanup_quiz_state() -> None:
    now = time.time()
    stale = [k for k, v in QUIZ_STATE.items() if now - v.get("ts", 0) > _QUIZ_TTL]
    for k in stale:
        QUIZ_STATE.pop(k, None)


def _build_question_keyboard(user_id: str, q_idx: int) -> InlineKeyboardMarkup:
    """Build inline keyboard with 4 answer options (A/B/C/D)."""
    buttons = [
        [InlineKeyboardButton(
            text=_LETTERS[i],
            callback_data=f"quiz|{user_id}|{q_idx}|{i}",
        )]
        for i in range(4)
    ]
    # Arrange 2 buttons per row for compactness
    rows = []
    for i in range(0, 4, 2):
        rows.append(buttons[i] + buttons[i + 1])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _question_text(state: dict) -> str:
    """Format the question message text."""
    q_idx = state["q_idx"]
    order = state["order"]
    real_idx = order[q_idx]
    question = QUIZ_QUESTIONS[real_idx]
    total = state["total"]
    score = state["score"]

    lines = [
        f" *Вопрос {q_idx + 1}/{total}* | Счёт: {score}/{q_idx}",
        f"{'─' * 32}",
        f"*{question['q']}*",
        "",
    ]
    for opt in question["opts"]:
        lines.append(opt)
    return "\n".join(lines)


@quiz_router.message(Command("quiz"))
async def quiz_start(message: types.Message) -> None:
    """Start a new quiz session for the user."""
    user_id = str(message.from_user.id)

    # Shuffle question order for this session
    order = list(range(len(QUIZ_QUESTIONS)))
    random.shuffle(order)

    state = {
        "q_idx": 0,
        "score": 0,
        "total": len(QUIZ_QUESTIONS),
        "msg_id": None,
        "order": order,
        "ts": time.time(),
    }
    QUIZ_STATE[user_id] = state

    _cleanup_quiz_state()

    text = _question_text(state)
    kb = _build_question_keyboard(user_id, 0)
    sent = await message.reply(text, parse_mode="Markdown", reply_markup=kb)
    QUIZ_STATE[user_id]["msg_id"] = sent.message_id


@quiz_router.callback_query(F.data.startswith("quiz|"))
async def quiz_answer(callback: types.CallbackQuery) -> None:
    """Handle quiz answer button press."""
    await callback.answer()

    parts = callback.data.split("|")
    if len(parts) != 4:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    _, cb_uid, cb_q_idx_str, cb_choice_str = parts

    # Security: only the owner of this quiz session can answer
    actual_uid = str(callback.from_user.id)
    if actual_uid != cb_uid:
        await callback.answer(" Это не ваш тест!", show_alert=True)
        return

    state = QUIZ_STATE.get(actual_uid)
    if not state:
        await callback.message.edit_text(
            " Сессия теста не найдена или истекла.\nНачните заново: /quiz",
            parse_mode="Markdown",
        )
        return

    # Validate that the callback matches the current question
    try:
        cb_q_idx = int(cb_q_idx_str)
        cb_choice = int(cb_choice_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    current_q_idx = state["q_idx"]
    if cb_q_idx != current_q_idx:
        # Stale button — user already answered this question
        await callback.answer(" Вы уже ответили на этот вопрос.", show_alert=True)
        return

    order = state["order"]
    real_idx = order[current_q_idx]
    question = QUIZ_QUESTIONS[real_idx]
    correct = question["correct"]
    is_correct = cb_choice == correct

    if is_correct:
        state["score"] += 1
        result_line = " *Правильно!*"
    else:
        correct_letter = _LETTERS[correct]
        correct_text = question["opts"][correct]
        result_line = f" *Неверно.* Правильный ответ: {correct_letter} — {correct_text}"

    score = state["score"]
    total = state["total"]
    q_num = current_q_idx + 1

    # Build feedback text
    feedback_lines = [
        f" *Вопрос {q_num}/{total}*",
        f"*{question['q']}*",
        "",
        result_line,
        "",
        f" {question['explain']}",
        "",
        f" Счёт: *{score}/{q_num}*",
    ]

    next_q_idx = current_q_idx + 1

    if next_q_idx >= total:
        # Quiz finished — show final results
        QUIZ_STATE.pop(actual_uid, None)

        pct = round(score / total * 100)
        if pct == 100:
            medal = " Отлично!"
        elif pct >= 70:
            medal = " Хорошо!"
        elif pct >= 40:
            medal = " Неплохо, но есть куда расти."
        else:
            medal = " Стоит подтянуть знания CFW."

        feedback_lines += [
            "─" * 32,
            f"🏁 *Тест завершён!*",
            f"Итог: *{score}/{total}* ({pct}%)",
            medal,
            "",
            "Пройти снова: /quiz",
        ]
        final_text = "\n".join(feedback_lines)
        await callback.message.edit_text(final_text, parse_mode="Markdown")
    else:
        # Advance to next question
        state["q_idx"] = next_q_idx
        state["ts"] = time.time()

        feedback_text = "\n".join(feedback_lines)
        await callback.message.edit_text(feedback_text, parse_mode="Markdown")

        # Send next question as a new message
        next_text = _question_text(state)
        kb = _build_question_keyboard(actual_uid, next_q_idx)
        sent = await callback.message.answer(next_text, parse_mode="Markdown", reply_markup=kb)
        state["msg_id"] = sent.message_id
