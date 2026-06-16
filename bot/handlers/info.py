"""Info and utility handlers: /start, /all, /stats, /help, /releases, /digest, /week, /compare, /tip, etc."""
import asyncio
import logging
import random
import time as _time
from collections import Counter

from aiogram import Router, types
from aiogram.filters import Command, CommandObject

from .. import storage
from ..config import GITHUB_REPO
from ..helpers import create_categories_keyboard, safe_send
from ..nlp import search_guides
from ..services.ai import ask_ai
from ..services.github import fetch_github_repos, fetch_changelog
from .discovery import compute_ratings

router = Router()


def _recommend_user() -> str:
    if GITHUB_REPO and "/" in GITHUB_REPO:
        return GITHUB_REPO.split("/")[0]
    return "Dimasick-git"


@router.message(Command("start"))
async def start(message: types.Message) -> None:
    total = sum(len(g) for g in storage.GUIDES.values())
    await message.reply(
        " *Ryazhenka Bot* — инженерный помощник по прошивке Nintendo Switch\n"
        f"{'─' * 35}\n"
        f" Загружено гайдов: *{total}* в *{len(storage.GUIDES)}* категориях\n\n"
        " *Основные команды:*\n"
        " /guide `<тема>` — найти гайд (fuzzy search)\n"
        " /aiguide `<текст>` — умный поиск (BM25 + fuzzy)\n"
        " /all — все категории\n"
        " /help — полный список команд\n\n"
        " *Выберите категорию ниже:*",
        parse_mode="Markdown",
        reply_markup=create_categories_keyboard(),
    )


@router.message(Command("all"))
async def show_all(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return
    text = " *Все категории* :\n\n"
    total = 0
    for cat, guides in storage.GUIDES.items():
        total += len(guides)
        text += f"{cat} — {len(guides)} гайдов\n"
    text += f"\n Всего: {total} гайдов в {len(storage.GUIDES)} категориях\n\n"
    text += "Используйте /guide <название> для поиска или выберите категорию:"
    await safe_send(message, text, reply_markup=create_categories_keyboard())


@router.message(Command("stats"))
async def guide_stats(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return
    total = sum(len(g) for g in storage.GUIDES.values())
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)
    text = f" *Статистика базы гайдов*\n{'─' * 30}\n Всего: *{total}*\n Категорий: *{len(storage.GUIDES)}*\n\n*Топ категорий:*\n"
    for cat, guides in sorted_cats[:8]:
        bar = "█" * min(len(guides) // max(1, total // 20), 10)
        text += f"  {cat} — {len(guides)} {bar}\n"
    if len(sorted_cats) > 8:
        text += f"  _...и ещё {len(sorted_cats) - 8} категорий_\n"
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("recommend"))
async def recommend_repos(message: types.Message) -> None:
    user = _recommend_user()
    await message.reply(f" Получаю публичные репозитории  {user}...")
    repos = await fetch_github_repos(user, limit=20)
    if not repos:
        await message.reply(" Не удалось получить репозитории.")
        return
    text = f" Рекомендуемые репозитории  {user}:\n\n"
    for name, url, desc in repos[:15]:
        text += f"• [{name}]({url}) — {desc}\n"
    await safe_send(message, text, disable_web_page_preview=True)


@router.message(Command("history"))
async def search_history_cmd(message: types.Message) -> None:
    user_id = str(message.from_user.id)
    history = storage.SEARCH_HISTORY.get(user_id, [])
    if not history:
        await message.reply(
            " *История поиска пуста.*\n\nИспользуй /guide или /aiguide чтобы искать гайды.",
            parse_mode="Markdown",
        )
        return
    text = " *Ваши последние запросы:*\n\n"
    for i, entry in enumerate(reversed(history[-10:]), 1):
        q = entry.get("query", "")
        text += f"{i}. `/guide {q}`\n"
    text += "\nНажмите на запрос чтобы повторить поиск."
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("releases"))
async def releases_command(message: types.Message) -> None:
    thinking_msg = await message.reply("⏳ Загружаю последние релизы Ryazhenka...")

    try:
        from ..services.github import fetch_ryazha_releases
        releases = await fetch_ryazha_releases()
    except Exception as e:
        logging.error("Failed to fetch releases: %s", e)
        await thinking_msg.edit_text("⚠️ Не удалось загрузить релизы. Попробуйте позже.")
        return

    if not releases:
        await thinking_msg.edit_text("ℹ️ Релизы пока не найдены.")
        return

    lines = ["🚀 *Последние релизы Ryazhenka*\n" + "─" * 35]

    for repo_full, release in releases[:10]:
        repo_name = repo_full.split("/")[-1]
        tag = release.get("tag", "—")
        date = release.get("date", "")
        url = release.get("url", "")
        prerelease = release.get("prerelease", False)

        pre_mark = " _[pre]_" if prerelease else ""
        lines.append(f"\n*{repo_name}*{pre_mark}")
        if url:
            lines.append(f"  [{tag}]({url}) · `{date}`")
        else:
            lines.append(f"  {tag} · `{date}`")

        for asset in release.get("assets", []):
            name = asset.get("name", "")
            dl_url = asset.get("url", "")
            size = asset.get("size", 0)
            if not name or not dl_url:
                continue
            if name.endswith((".nro", ".zip", ".7z")):
                size_mb = size / (1024 * 1024) if size else 0
                size_str = f" `{size_mb:.1f}MB`" if size_mb > 0 else ""
                lines.append(f"  📦 [{name}]({dl_url}){size_str}")
                break

    lines.append("\n_Данные кэшируются на 1 час_")

    await thinking_msg.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@router.message(Command("digest"))
async def digest_command(message: types.Message) -> None:
    """Персональный дайджест: последние поиски + AI-рекомендации + топ гайдов."""
    user_id = str(message.from_user.id)

    lines = [" *Ваш персональный дайджест*\n" + "─" * 35]

    history = storage.SEARCH_HISTORY.get(user_id, [])
    recent_queries = []
    if history:
        lines.append("\n *Ваши последние поиски:*")
        for entry in list(reversed(history))[:5]:
            q = entry.get("query", "")
            if q:
                lines.append(f"  `/guide {q}`")
                recent_queries.append(q)
    else:
        lines.append("\n _Поисковая история пуста — попробуйте /guide_")

    if recent_queries:
        try:
            rec_prompt = (
                f"Пользователь искал в боте по Nintendo Switch CFW: {', '.join(recent_queries[:3])}.\n"
                "На основе этих тем порекомендуй 2-3 смежных темы которые могут быть полезны "
                "для изучения. Формат: короткий список тем (1 строка каждая). "
                "Без введения, только темы."
            )
            ai_rec = await ask_ai(rec_prompt)
            if ai_rec:
                lines.append("\n🤖 *AI рекомендует изучить:*")
                for rec_line in ai_rec.strip().split("\n")[:3]:
                    rec_line = rec_line.strip().lstrip("•-– ").strip()
                    if rec_line:
                        lines.append(f"  • `/guide {rec_line}`")
        except Exception:
            pass

    scores, meta = compute_ratings()
    if scores:
        top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("\n🔥 *Трендовые гайды:*")
        for key, sc in top3:
            m = meta.get(key, {})
            title = m.get("title", key)
            url = m.get("url", "")
            rating_val = storage.GUIDE_RATINGS.get(key, {})
            up = rating_val.get("up", 0) if isinstance(rating_val, dict) else 0
            down = rating_val.get("down", 0) if isinstance(rating_val, dict) else 0
            if url:
                lines.append(f"  [{title}]({url}) — 👍{up} 👎{down}")
            else:
                lines.append(f"  {title} — 👍{up} 👎{down}")
    else:
        lines.append("\n _Нет оценённых гайдов — оцени любой через /guide_")

    all_cats = [c for c, g in storage.GUIDES.items() if g]
    if len(all_cats) >= 2:
        chosen_cats = random.sample(all_cats, 2)
        lines.append("\n *Случайные гайды для вас:*")
        for cat in chosen_cats:
            entries = [(t, u) for t, u in storage.GUIDES[cat].items() if u]
            if entries:
                title, url = random.choice(entries)
                lines.append(f"  [{title}]({url}) — _{cat}_")
    elif all_cats:
        entries = [(t, u) for t, u in storage.GUIDES[all_cats[0]].items() if u]
        if entries:
            lines.append("\n *Случайный гайд:*")
            title, url = random.choice(entries)
            lines.append(f"  [{title}]({url})")

    lines.append("\n _Используй /quiz чтобы проверить знания CFW!_")

    await safe_send(message, "\n".join(lines), disable_web_page_preview=True)


@router.message(Command("week"))
async def week_command(message: types.Message) -> None:
    """Недельная статистика: топ поисков, лучшие гайды, активность."""
    lines = ["📊 *Недельная активность*\n" + "─" * 35]

    week_ago = _time.time() - 7 * 86400
    all_queries: list = []
    for uid, entries in storage.SEARCH_HISTORY.items():
        for entry in entries:
            if entry.get("ts", 0) >= week_ago:
                q = entry.get("query", "").strip()
                if q:
                    all_queries.append(q.lower())

    if all_queries:
        top_queries = Counter(all_queries).most_common(5)
        lines.append("\n🔍 *Топ поисков за неделю:*")
        for i, (q, cnt) in enumerate(top_queries, 1):
            lines.append(f"  {i}. `{q}` — {cnt} раз{'а' if cnt > 1 else ''}")
    else:
        lines.append("\n _Нет данных о поисках за последнюю неделю_")

    scores, meta = compute_ratings()
    if scores:
        top5 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        lines.append("\n⭐ *Лучшие гайды по оценкам:*")
        for i, (key, sc) in enumerate(top5, 1):
            m = meta.get(key, {})
            title = m.get("title", key)
            url = m.get("url", "")
            rating_val = storage.GUIDE_RATINGS.get(key, {})
            up = rating_val.get("up", 0) if isinstance(rating_val, dict) else 0
            if url:
                lines.append(f"  {i}. [{title}]({url}) — 👍 {up}")
            else:
                lines.append(f"  {i}. {title} — 👍 {up}")

    total_cats = len(storage.GUIDES)
    total_guides = sum(len(g) for g in storage.GUIDES.values())
    total_users = len(storage.SEARCH_HISTORY)
    total_week_searches = len(all_queries)

    lines.append(f"\n📚 *База знаний:*")
    lines.append(f"  Категорий: *{total_cats}* · Гайдов: *{total_guides}*")
    lines.append(f"  Пользователей: *{total_users}* · Поисков за неделю: *{total_week_searches}*")

    lines.append("\n _Обновляется каждую неделю. Используй /trending для топа!_")

    await safe_send(message, "\n".join(lines), disable_web_page_preview=True)


@router.message(Command("compare"))
async def compare_command(message: types.Message, command: CommandObject) -> None:
    """Сравнивает два инструмента/CFW с помощью AI."""
    args = (command.args or "").strip()
    if not args:
        await message.reply(
            " *Сравнение инструментов Switch CFW*\n\n"
            "Использование:\n"
            "`/compare emuNAND vs sysNAND`\n"
            "`/compare Atmosphere и Hekate`\n"
            "`/compare Tinfoil, Goldleaf`\n\n"
            "Разделители: `vs`, `и`, `,`",
            parse_mode="Markdown",
        )
        return

    topic1: str = ""
    topic2: str = ""
    for sep in (" vs ", " и ", ","):
        if sep in args:
            parts = args.split(sep, 1)
            topic1 = parts[0].strip()
            topic2 = parts[1].strip()
            break

    if not topic1 or not topic2:
        await message.reply(
            f" Не удалось разобрать два инструмента из: «{args}»\n\n"
            "Пример: `/compare emuNAND vs sysNAND`",
            parse_mode="Markdown",
        )
        return

    thinking_msg = await message.reply(f" Сравниваю *{topic1}* и *{topic2}*...", parse_mode="Markdown")

    prompt = (
        f"Сравни два инструмента/понятия Nintendo Switch CFW: «{topic1}» и «{topic2}».\n"
        "Структура ответа:\n"
        f"1. Что такое {topic1} (1-2 предложения)\n"
        f"2. Что такое {topic2} (1-2 предложения)\n"
        "3. Ключевые отличия (3-5 пунктов)\n"
        "4. Когда использовать каждый\n"
        "Отвечай по-русски, кратко и практично."
    )

    ai_answer = await ask_ai(prompt)

    if ai_answer:
        reply_text = (
            f" *Сравнение: {topic1} vs {topic2}*\n"
            f"{'─' * 35}\n\n"
            f"{ai_answer}"
        )
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown")
    else:
        await thinking_msg.edit_text(
            " AI временно недоступен.\n"
            "Попробуй:\n"
            f"• `/ask что такое {topic1}`\n"
            f"• `/ask что такое {topic2}`",
            parse_mode="Markdown",
        )


_CFW_TIPS = [
    "💡 Всегда делай резервную копию NAND через Hekate перед обновлением CFW — это спасёт от кирпича.",
    "💡 Используй emuNAND для игры в пиратские игры. sysNAND с CFW онлайн = риск бана от Nintendo.",
    "💡 90DNS (90.130.70.73) блокирует серверы Nintendo и защищает от бана при онлайн-игре в emuNAND.",
    "💡 Sigpatches нужно обновлять вместе с каждым обновлением Atmosphere — иначе игры не запустятся.",
    "💡 AIO-Switch-Updater обновляет все компоненты Ryazhenka CFW за одно нажатие прямо на Switch.",
    "💡 FPSLocker позволяет залочить игру на 30 FPS для стабильного геймплея или сэкономить заряд.",
    "💡 RyazhaTune воспроизводит MP3/FLAC прямо во время игры — добавь музыку в /music на SD-карте.",
    "💡 Tesla overlay открывается комбо L + DDOWN + RS — не выходя из игры.",
    "💡 Mission-Control позволяет подключить контроллер PS5/Xbox к Switch по Bluetooth без адаптеров.",
    "💡 Fizeau настраивает фильтр синего света на экране Switch — удобно для игры вечером.",
    "💡 Ryazha-Status-Monitor в Full-режиме показывает нагрузку всех 4 ядер CPU, GPU и температуру.",
    "💡 ovlSysmodules позволяет включать/отключать sysmodule без перезагрузки консоли.",
    "💡 DBI — самый быстрый установщик игр через USB MTP, работает без дополнительных драйверов.",
    "💡 EdiZon поддерживает скрипты Lua для сложных чит-кодов — база читов хранится на SD-карте.",
    "💡 ReverseNX-RT принудительно включает TV-режим при работе без дока для максимальной производительности.",
    "💡 Lockpick_RCM дампит prod.keys и title.keys — они нужны для работы эмуляторов Ryujinx и Yuzu.",
    "💡 SaltyNX нужен для работы Ryazha-Status-Monitor и некоторых других plагинов — установи его первым.",
    "💡 libryazhahand использует namespace /config/ryazhahand/ — не смешивай с /config/ultrahand/.",
    "💡 Ryazhahand-Overlay поддерживает PNG-обои на фоне меню — положи файл wallpaper.png в config.",
    "💡 Модчип (Picofly/Hwfly) нужен для патченных Switch (V2/Lite/OLED) — на V1 достаточно jig + RCM.",
    "💡 TegraRcmGUI + jig — самый простой способ войти в RCM и запустить Hekate на Switch V1.",
    "💡 NSP — это формат цифровых игр из eShop, XCI — дамп картриджа. Оба ставятся через Tinfoil/DBI.",
    "💡 Goldleaf + Quark позволяют установить NSP по USB с ПК без специальных драйверов.",
    "💡 Ryazha-cheker отслеживает все коммиты Ryazhenka и присылает уведомления в Telegram автоматически.",
    "💡 После обновления системного ПО Switch нужно обновить Atmosphere, Hekate и sigpatches одновременно.",
    "💡 emuMMC лучше создавать на отдельном разделе SD-карты (не в папке) — так быстрее и надёжнее.",
    "💡 Для защиты от бана отключи автообновление системы в настройках Nintendo Switch (sysNAND).",
    "💡 RCU (Ryazha Clock Utility) — улучшенный форк sys-clk с FPS-aware VRR ladder для автоматического разгона.",
    "💡 Используй /quiz в боте чтобы проверить знания Nintendo Switch CFW и изучить новое!",
    "💡 Atmosphere-RYZ — preconf-форк Atmosphere от команды Ryazhenka, настроенный под Ryazhenka CFW из коробки.",
]


@router.message(Command("tip"))
async def tip_command(message: types.Message) -> None:
    """Случайный совет по Nintendo Switch CFW и Ryazhenka."""
    tip = random.choice(_CFW_TIPS)
    await message.reply(
        f"💡 *Совет дня по Switch CFW*\n{'─' * 35}\n\n{tip}\n\n"
        "_Ещё совет: /tip · Тест знаний: /quiz_",
        parse_mode="Markdown",
    )


_HOWTO_STEPS = {
    "rcm": (
        "🔓 *Взлом через RCM (Switch V1 непатченный)*\n"
        "─" * 35 + "\n\n"
        "Подходит для Switch V1 (2017–2018) с уязвимостью fusée-gelée.\n\n"
        "*Шаг 1.* Скачайте с GitHub: Hekate, Atmosphere, sigpatches\n"
        "*Шаг 2.* Распакуйте архивы на SD-карту (корень)\n"
        "*Шаг 3.* Установите jig (RCM замыкатель) в правый Joy-Con слот\n"
        "*Шаг 4.* Зажмите `Vol+` и нажмите `Power` — Switch войдёт в RCM\n"
        "*Шаг 5.* Подключите Switch к ПК, запустите TegraRcmGUI\n"
        "*Шаг 6.* Перетащите `hekate_ctcaer_*.bin` в TegraRcmGUI → Inject\n"
        "*Шаг 7.* В меню Hekate: `Launch → Atmosphere FSS0 emuMMC`\n\n"
        "📌 Рекомендуем создать emuMMC через `Tools → Partition SD Card`\n"
        "⚠️ Обязательно сделайте NAND backup: `Tools → Backup → eMMC BOOT0&1 + eMMC RAW GPP`"
    ),
    "modchip": (
        "🔧 *Взлом через ModChip (патченный Switch / Lite / OLED)*\n"
        "─" * 35 + "\n\n"
        "Подходит для Switch V2, Lite, OLED где RCM недоступен.\n\n"
        "*Шаг 1.* Купите ModChip: Picofly (RP2040/RP2350), Hwfly или SX Core\n"
        "*Шаг 2.* Установите ModChip (требует пайки — обратитесь к мастеру)\n"
        "*Шаг 3.* После установки ModChip запускается автоматически при включении\n"
        "*Шаг 4.* Скачайте Ryazhenka CFW: /download\n"
        "*Шаг 5.* Распакуйте архив на SD-карту (корень)\n"
        "*Шаг 6.* Включите Switch — Hekate загрузится автоматически\n"
        "*Шаг 7.* В меню Hekate: `Launch → Atmosphere FSS0 emuMMC`\n\n"
        "⚠️ Установка ModChip аннулирует гарантию Nintendo"
    ),
    "emummc": (
        "💾 *Создание emuMMC (рекомендуется)*\n"
        "─" * 35 + "\n\n"
        "emuMMC изолирует CFW от sysNAND, защищая от бана.\n\n"
        "*Шаг 1.* Загрузитесь в Hekate (через RCM или ModChip)\n"
        "*Шаг 2.* `Tools → Partition SD Card`\n"
        "*Шаг 3.* Установите emuMMC (File-based): перетащите ползунок\n"
        "*Шаг 4.* Нажмите `Next Step → Start` — ждите завершения\n"
        "*Шаг 5.* `emuMMC → Create emuMMC → SD File Based`\n"
        "*Шаг 6.* После создания: `Launch → Atmosphere FSS0 emuMMC`\n\n"
        "✅ emuMMC создан! Пиратские игры устанавливайте только сюда."
    ),
    "sigpatches": (
        "🔑 *Установка sigpatches*\n"
        "─" * 35 + "\n\n"
        "Sigpatches нужны для запуска неподписанных (пиратских) игр.\n\n"
        "*Шаг 1.* Скачайте через AIO-Switch-Updater (`/guide aio updater`)\n"
        "   *или* вручную с sigmapatches.coomer.party\n"
        "*Шаг 2.* Распакуйте архив на SD-карту (корень)\n"
        "*Шаг 3.* Перезагрузите Switch в CFW\n\n"
        "⚠️ Sigpatches нужно обновлять при каждом обновлении Atmosphere!"
    ),
    "dns": (
        "🛡️ *Настройка 90DNS (защита от бана)*\n"
        "─" * 35 + "\n\n"
        "90DNS блокирует серверы Nintendo и защищает от бана.\n\n"
        "*Шаг 1.* На Switch: `Настройки → Интернет → Параметры интернета`\n"
        "*Шаг 2.* Выберите вашу сеть Wi-Fi → `Изменить настройки`\n"
        "*Шаг 3.* `DNS → Вручную`\n"
        "*Шаг 4.* Основной DNS: `90.130.70.73`\n"
        "*Шаг 5.* Дополнительный DNS: `90.130.70.73`\n"
        "*Шаг 6.* Сохраните и переподключитесь\n\n"
        "✅ Проверка: Настройки → Интернет → Проверить соединение\n"
        "   Должно появиться 'Интернет недоступен' (это нормально!)"
    ),
}


@router.message(Command("howto"))
async def howto_command(message: types.Message, command: CommandObject) -> None:
    """Пошаговые руководства по Switch CFW."""
    arg = (command.args or "").strip().lower()

    if not arg:
        await message.reply(
            "📖 *Пошаговые руководства Ryazhenka CFW*\n"
            "─" * 35 + "\n\n"
            "Выберите тему:\n\n"
            "🔓 `/howto rcm` — Взлом через RCM (V1)\n"
            "🔧 `/howto modchip` — Взлом через ModChip (V2/Lite/OLED)\n"
            "💾 `/howto emummc` — Создание emuMMC\n"
            "🔑 `/howto sigpatches` — Установка sigpatches\n"
            "🛡️ `/howto dns` — Настройка 90DNS (защита от бана)\n\n"
            "💡 Пример: `/howto rcm`\n\n"
            "📚 Полная документация: /help",
            parse_mode="Markdown",
        )
        return

    step_text = _HOWTO_STEPS.get(arg)
    if step_text:
        await message.reply(
            step_text + "\n\n_Другие руководства: /howto_",
            parse_mode="Markdown",
        )
    else:
        available = ", ".join(f"`{k}`" for k in _HOWTO_STEPS)
        await message.reply(
            f"❓ Руководство `{arg}` не найдено.\n\n"
            f"Доступные темы: {available}\n\n"
            "Введите `/howto` для списка всех руководств.",
            parse_mode="Markdown",
        )


def _classify_commit(message: str) -> str:
    """Classify a commit message into an emoji category."""
    lower = message.lower()
    if any(k in lower for k in ("feat", "add", "new", "добав", "новый", "новая")):
        return "✨"
    if any(k in lower for k in ("fix", "bug", "hotfix", "patch", "исправ", "баг", "фикс")):
        return "🐛"
    if any(k in lower for k in ("refactor", "clean", "rework", "рефактор", "перераб")):
        return "♻️"
    if any(k in lower for k in ("update", "bump", "upgrade", "обновл", "актуал")):
        return "📦"
    if any(k in lower for k in ("docs", "readme", "документ", "доку")):
        return "📝"
    if any(k in lower for k in ("perf", "optim", "speed", "произв", "оптим")):
        return "⚡"
    if any(k in lower for k in ("release", "version", "релиз", "версия")):
        return "🚀"
    return "🔹"


@router.message(Command("changelog"))
async def changelog_command(message: types.Message) -> None:
    """Последние коммиты по ключевым репозиториям Ryazhenka."""
    thinking_msg = await message.reply("⏳ Получаю последние изменения...")

    try:
        repo_commits = await fetch_changelog()
    except Exception as e:
        logging.error("changelog_command: %s", e)
        await thinking_msg.edit_text("⚠️ Не удалось загрузить changelog. Попробуйте позже.")
        return

    if not repo_commits:
        await thinking_msg.edit_text("ℹ️ Нет свежих изменений.")
        return

    lines = ["📋 *Changelog Ryazhenka*\n" + "─" * 35]

    for repo_full, commits in repo_commits[:8]:
        repo_name = repo_full.split("/")[-1]
        repo_url = f"https://github.com/{repo_full}"
        lines.append(f"\n[*{repo_name}*]({repo_url})")
        for c in commits[:2]:
            icon = _classify_commit(c["message"])
            sha = c["sha"]
            msg = c["message"][:60]
            date = c["date"]
            url = c["url"]
            lines.append(f"  {icon} [{sha}]({url}) {msg} `{date}`")

    lines.append("\n_Кэш: 15 мин · Больше: /releases_")

    await thinking_msg.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@router.message(Command("help"))
async def help_command(message: types.Message) -> None:
    text = (
        " *Полный список команд* \n"
        f"{'─' * 35}\n"
        " *Основные:*\n"
        " /start — Приветствие и быстрые ссылки\n"
        " /all — Показать все категории\n"
        " /guide `<тема>` — Найти гайд (fuzzy + BM25)\n"
        " /aiguide `<текст>` — Умный поиск + AI если гайд не найден\n"
        " /ask `<вопрос>` — Задать вопрос AI по Switch CFW (с контекстом)\n"
        "🔄 /ask\_reset — Сбросить контекст разговора с AI\n"
        " /random `[категория]` — Случайный гайд\n"
        "🆕 /new — Последние добавленные гайды\n"
        " /stats — Статистика базы гайдов\n"
        " /top — Топ категорий\n"
        " /category `<название>` — Гайды по категории (с пагинацией)\n"
        " /cat `<название>` — Псевдоним /category\n"
        "🔥 /trending — Топ гайдов по оценкам\n"
        " /history — Ваши последние поисковые запросы\n"
        " /recommend — Репозитории автора\n"
        "🚀 /releases — Последние релизы Ryazhenka\n"
        "📋 /changelog — Свежие коммиты по репозиториям\n"
        "⬇️ /download — Скачать последний релиз CFW\n"
        "🧩 /modules — Все модули с версиями и ссылками\n\n"
        "⭐ *Избранное:*\n"
        "/fav — Показать избранное\n"
        "/fav add `<тема>` — Добавить гайд\n"
        "/fav remove `<номер>` — Удалить\n\n"
        " *Интерактивные функции:*\n"
        "💡 /tip — Случайный совет по Switch CFW\n"
        " /quiz — Тест знаний по Switch CFW (43 вопроса)\n"
        " /digest — Персональный дайджест гайдов\n"
        " /week — Недельная статистика и топ поисков\n"
        " /compare `<A>` vs `<B>` — Сравнить два инструмента/CFW\n"
        "📖 /howto `<тема>` — Пошаговые руководства (rcm/modchip/emummc/sigpatches/dns)\n\n"
        " *Обратная связь:*\n"
        "/feedback `<текст>` — Предложить новый гайд\n\n"
        " *Inline-режим:*\n"
        "Напиши `@botname запрос` в любом чате!\n\n"
        " *Админ-команды:*\n"
        "/sync, /add\\_guide, /remove\\_guide, /edit\\_guide, /list\\_guides, /admin\\_help\n"
    )
    await message.reply(text, parse_mode="Markdown")
