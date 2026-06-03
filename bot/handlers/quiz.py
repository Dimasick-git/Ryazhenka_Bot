"""Interactive quiz about Nintendo Switch CFW topics."""
import random
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

quiz_router = Router()

# ── Quiz questions (all in Russian) ───────────────────────────────────────────
QUIZ_QUESTIONS = [
    {
        "q": "Что такое emuNAND?",
        "opts": [
            "A. Эмуляция NAND на SD-карте",
            "B. Встроенная память Nintendo Switch",
            "C. Утилита для резервного копирования",
            "D. Тип картриджа для Switch",
        ],
        "correct": 0,
        "explain": (
            "emuNAND (Emulated NAND) — это полная эмуляция встроенной памяти консоли "
            "на SD-карте. Позволяет запускать CFW изолированно от оригинальной прошивки "
            "и защищает от бана при использовании пиратских игр."
        ),
    },
    {
        "q": "Что такое Atmosphere?",
        "opts": [
            "A. Игра для Nintendo Switch",
            "B. Кастомная прошивка (CFW) для Nintendo Switch",
            "C. Официальное обновление прошивки от Nintendo",
            "D. Приложение для управления SD-картой",
        ],
        "correct": 1,
        "explain": (
            "Atmosphere — наиболее популярная кастомная прошивка (CFW) для Nintendo Switch, "
            "разработанная командой Atmosphère-NX. Она позволяет запускать homebrew, "
            "моды и неподписанный код на консоли."
        ),
    },
    {
        "q": "Что делает sys-clk?",
        "opts": [
            "A. Синхронизирует время с интернетом",
            "B. Управляет тактовыми частотами CPU/GPU/RAM",
            "C. Делает резервную копию сохранений",
            "D. Загружает системные модули",
        ],
        "correct": 1,
        "explain": (
            "sys-clk — это системный модуль Atmosphere, который позволяет управлять "
            "тактовыми частотами процессора (CPU), видеочипа (GPU) и оперативной памяти (RAM). "
            "Используется для разгона и снижения энергопотребления."
        ),
    },
    {
        "q": "Что такое sigpatch (сигпатч)?",
        "opts": [
            "A. Патч для улучшения Wi-Fi сигнала",
            "B. Официальное обновление безопасности от Nintendo",
            "C. Патч для запуска неподписанного (пиратского) кода",
            "D. Файл конфигурации Atmosphere",
        ],
        "correct": 2,
        "explain": (
            "Sigpatches (signature patches) — это патчи, которые обходят проверку "
            "криптографической подписи Nintendo при запуске игр. Они позволяют "
            "запускать неподписанный код, включая NSP-образы и XCI-образы."
        ),
    },
    {
        "q": "Что такое Hekate?",
        "opts": [
            "A. Homebrew-игра для Nintendo Switch",
            "B. Утилита для резервного копирования игр",
            "C. Кастомный загрузчик (bootloader) для Nintendo Switch",
            "D. Менеджер файлов на SD-карте",
        ],
        "correct": 2,
        "explain": (
            "Hekate — кастомный загрузчик (bootloader) для Nintendo Switch. "
            "Позволяет загружать различные прошивки, создавать резервные копии NAND, "
            "управлять разделами SD-карты и настраивать параметры запуска."
        ),
    },
    {
        "q": "Что делает FPSLocker?",
        "opts": [
            "A. Блокирует запуск игр без интернета",
            "B. Устанавливает лимит кадров в секунду (FPS) в играх",
            "C. Синхронизирует сохранения в облако",
            "D. Разгоняет GPU для увеличения FPS",
        ],
        "correct": 1,
        "explain": (
            "FPSLocker — это оверлей для Tesla, который позволяет устанавливать "
            "ограничение (лок) кадров в секунду для конкретных игр. "
            "Например, можно залочить 30 FPS для стабильного геймплея или снизить "
            "до 20 FPS для экономии заряда."
        ),
    },
    {
        "q": "Что такое sysNAND?",
        "opts": [
            "A. Системный модуль для управления файлами",
            "B. Тип SD-карты для Nintendo Switch",
            "C. Оригинальная встроенная память Nintendo Switch",
            "D. Раздел SD-карты под emuNAND",
        ],
        "correct": 2,
        "explain": (
            "sysNAND (System NAND) — оригинальная встроенная флеш-память Nintendo Switch, "
            "где хранятся системная прошивка, данные пользователей и лицензии игр. "
            "В отличие от emuNAND, изменения в sysNAND напрямую влияют на реальную консоль."
        ),
    },
    {
        "q": "Что такое Tesla Overlay?",
        "opts": [
            "A. Официальный магазин Nintendo для Switch",
            "B. Система отображения оверлеев поверх запущенных игр",
            "C. Эмулятор для запуска игр 3DS",
            "D. Инструмент для редактирования сохранений",
        ],
        "correct": 1,
        "explain": (
            "Tesla — это фреймворк для отображения оверлеев поверх запущенных игр "
            "на Nintendo Switch. Через Tesla-меню можно запускать плагины вроде "
            "FPSLocker, sys-clk overlay, EdiZon и другие, не выходя из игры."
        ),
    },
    {
        "q": "Для чего нужен режим RCM (Recovery Mode)?",
        "opts": [
            "A. Для восстановления официальной прошивки через интернет",
            "B. Для загрузки пейлоадов через USB-подключение к ПК",
            "C. Для сброса настроек консоли до заводских",
            "D. Для синхронизации Joy-Con контроллеров",
        ],
        "correct": 1,
        "explain": (
            "RCM (Recovery Mode / ReCovery Mode) — специальный режим Tegra X1, "
            "через который можно загружать пейлоады (например Hekate) с ПК по USB "
            "с помощью инструментов типа TegraRcmGUI или Tegra Smash. "
            "Используется для первого запуска CFW."
        ),
    },
    {
        "q": "Что такое Tinfoil?",
        "opts": [
            "A. Утилита для разгона процессора Switch",
            "B. Официальный браузер Nintendo Switch",
            "C. Менеджер и установщик NSP/XCI игр для Switch",
            "D. Программа для управления Bluetooth-устройствами",
        ],
        "correct": 2,
        "explain": (
            "Tinfoil — популярный менеджер и установщик игр для Nintendo Switch, "
            "работающий в среде CFW. Позволяет устанавливать NSP и XCI образы игр, "
            "управлять библиотекой установленных тайтлов и загружать игры из сети."
        ),
    },
]

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
