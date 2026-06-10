"""Download and modules handlers: /download, /modules."""
import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..helpers import escape_html
from ..services.github import fetch_latest_release, fetch_ryazha_releases

router = Router()

_RYAZHA_MODULES = [
    {
        "name": "Ryazhahand-Overlay",
        "repo": "Dimasick-git/Ryazhahand-Overlay",
        "desc": "Tesla overlay меню — оверлеи, настройки, LED и аудио паки.",
        "icon": "🎮",
    },
    {
        "name": "RCU",
        "repo": "Dimasick-git/RCU",
        "desc": "Ryazha Clock Utility — CPU/GPU/RAM с FPS-aware VRR и профилями под игру.",
        "icon": "⚡",
    },
    {
        "name": "Ryazha-Status-Monitor",
        "repo": "Dimasick-git/Ryazha-Status-Monitor",
        "desc": "CPU/GPU температура, частоты, FPS и заряд батареи в реальном времени.",
        "icon": "📊",
    },
    {
        "name": "RyazhaTune",
        "repo": "Dimasick-git/RyazhaTune",
        "desc": "Плеер MP3/FLAC/WAV с фоновым воспроизведением через оверлей.",
        "icon": "🎵",
    },
    {
        "name": "Mission-Control",
        "repo": "Dimasick-git/Mission-Control",
        "desc": "Подключение PS5/Xbox/Switch Pro по Bluetooth без адаптеров.",
        "icon": "🕹️",
    },
    {
        "name": "FPSLocker",
        "repo": "Dimasick-git/FPSLocker",
        "desc": "Лок FPS на 30/60 и настройка VSync для стабильного геймплея.",
        "icon": "🔒",
    },
    {
        "name": "EdiZon",
        "repo": "Dimasick-git/EdiZon",
        "desc": "Менеджер читов, сохранений и Lua-скриптов.",
        "icon": "✏️",
    },
    {
        "name": "ovlSysmodules",
        "repo": "Dimasick-git/ovlSysmodules",
        "desc": "Включение/отключение sysmodule без перезагрузки консоли.",
        "icon": "🔧",
    },
    {
        "name": "Fizeau",
        "repo": "Dimasick-git/Fizeau",
        "desc": "Фильтр синего света и настройка цветовой температуры экрана.",
        "icon": "🌅",
    },
    {
        "name": "SwitchWave",
        "repo": "Dimasick-git/SwitchWave",
        "desc": "Аудио плагин для Nintendo Switch.",
        "icon": "🌊",
    },
    {
        "name": "nx-ovlloader",
        "repo": "Dimasick-git/nx-ovlloader",
        "desc": "Sysmodule загрузки Tesla overlay. Ryazha-edition форк ppkantorski.",
        "icon": "📦",
    },
    {
        "name": "libryazhahand",
        "repo": "Dimasick-git/libryazhahand",
        "desc": "Tesla overlay библиотека с namespace /config/ryazhahand/.",
        "icon": "📚",
    },
]


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@router.message(Command("download"))
async def download_command(message: types.Message) -> None:
    """Последний релиз Ryazhenka CFW с прямыми ссылками для скачивания."""
    thinking_msg = await message.reply("⏳ Получаю последний релиз Ryazhenka CFW...")

    try:
        release = await fetch_latest_release("Dimasick-git/Ryzhenka")
    except Exception as e:
        logging.error("download_command: %s", e)
        await thinking_msg.edit_text("⚠️ Не удалось получить информацию о релизе. Попробуйте позже.")
        return

    if not release:
        await thinking_msg.edit_text(
            "⚠️ Релизы не найдены.\n"
            "Проверьте: https://github.com/Dimasick-git/Ryzhenka/releases"
        )
        return

    tag = escape_html(release.get("tag", "—"))
    name = release.get("name", "")
    url = release.get("url", "")
    date = release.get("date", "")
    is_pre = release.get("prerelease", False)
    assets = release.get("assets", [])

    lines = [
        "📦 <b>Ryazhenka CFW</b> — Последний релиз",
        "─" * 30,
        f"🏷 Версия: <b>{tag}</b>" + (" <i>(pre-release)</i>" if is_pre else ""),
    ]
    if name and name != release.get("tag", ""):
        lines.append(f"📝 {escape_html(name)}")
    if date:
        lines.append(f"📅 Дата: {date}")

    if assets:
        lines.append("\n⬇️ <b>Файлы для скачивания:</b>")
        for asset in assets[:6]:
            size_str = f" ({_fmt_size(asset['size'])})" if asset.get("size") else ""
            a_name = escape_html(asset.get("name", ""))
            a_url = asset.get("url", "")
            if a_url:
                lines.append(f"• <a href='{a_url}'>{a_name}</a>{size_str}")
    else:
        if url:
            lines.append(f"\n<a href='{url}'>Открыть страницу релиза →</a>")

    lines.append(
        "\n🔗 <a href='https://github.com/Dimasick-git/Ryzhenka/releases'>Все релизы на GitHub</a>"
    )

    text = "\n".join(lines)

    kb_buttons = []
    if url:
        kb_buttons.append([InlineKeyboardButton(text="🌐 Открыть на GitHub", url=url)])
    for asset in assets[:3]:
        a_url = asset.get("url", "")
        a_name = asset.get("name", "")
        if a_url and a_name:
            kb_buttons.append([InlineKeyboardButton(text=f"⬇️ {a_name[:45]}", url=a_url)])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons) if kb_buttons else None
    await thinking_msg.edit_text(
        text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )


@router.message(Command("modules"))
async def modules_command(message: types.Message) -> None:
    """Все модули Ryazhenka с версиями и ссылками для скачивания."""
    thinking_msg = await message.reply("⏳ Загружаю информацию о модулях...")

    try:
        releases = await fetch_ryazha_releases()
    except Exception as e:
        logging.error("modules_command: %s", e)
        releases = []

    release_map = {r[0]: r[1] for r in releases}

    lines = ["🧩 <b>Модули Ryazhenka CFW</b>", "─" * 30]

    kb_buttons = []
    for mod in _RYAZHA_MODULES:
        icon = mod["icon"]
        name = mod["name"]
        repo = mod["repo"]
        desc = mod["desc"]

        rel = release_map.get(repo)
        version = escape_html(rel["tag"]) if rel else "—"
        gh_url = f"https://github.com/{repo}"

        lines.append(f"\n{icon} <b><a href='{gh_url}'>{escape_html(name)}</a></b>  <code>{version}</code>")
        lines.append(f"   {escape_html(desc)}")

        if rel and rel.get("assets"):
            first_asset = rel["assets"][0]
            a_url = first_asset.get("url", "")
            if a_url:
                kb_buttons.append(
                    [InlineKeyboardButton(text=f"⬇️ {name}", url=a_url)]
                )

    lines.append("\n\n📦 <b>Главный релиз CFW:</b> /download")
    lines.append("🚀 <b>Все релизы:</b> /releases")

    text = "\n".join(lines)

    # Keep only first 8 buttons to avoid oversized keyboard
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons[:8]) if kb_buttons else None
    await thinking_msg.edit_text(
        text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb
    )
