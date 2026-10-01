"""
Telegram Bot для мониторинга и получения серверов PESOK VPN
Парсит актуальные серверы и их пинг с сайта: https://sever-xd.github.io/pesok_auto_sub/

Автор: sever-xd
"""

import asyncio
import logging
import os
import time
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================================
# НАСТРОЙКИ
# ============================================================
# Токен бота (можно задать через переменную окружения BOT_TOKEN или вставить напрямую сюда)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_ОТ_BOTFATHER")

SITE_DATA_URL = "https://sever-xd.github.io/pesok_auto_sub/site_data.json"
SUB_URL = "https://sever-xd.github.io/pesok_auto_sub/subscription.txt"
WEBSITE_URL = "https://sever-xd.github.io/pesok_auto_sub/"

# Словарь стран и флагов
COUNTRY_NAMES = {
    "US": ("🇺🇸", "США"), "DE": ("🇩🇪", "Германия"), "NL": ("🇳🇱", "Нидерланды"),
    "FR": ("🇫🇷", "Франция"), "GB": ("🇬🇧", "Великобритания"), "JP": ("🇯🇵", "Япония"),
    "SG": ("🇸🇬", "Сингапур"), "KR": ("🇰🇷", "Южная Корея"), "HK": ("🇭🇰", "Гонконг"),
    "TW": ("🇹🇼", "Тайвань"), "CA": ("🇨🇦", "Канада"), "AU": ("🇦🇺", "Австралия"),
    "FI": ("🇫🇮", "Финляндия"), "SE": ("🇸🇪", "Швеция"), "TR": ("🇹🇷", "Турция"),
    "IN": ("🇮🇳", "Индия"), "PL": ("🇵🇱", "Польша"), "IT": ("🇮🇹", "Италия"),
    "ES": ("🇪🇸", "Испания"), "CH": ("🇨🇭", "Швейцария"), "AT": ("🇦🇹", "Австрия"),
    "NO": ("🇳🇴", "Норвегия"), "AE": ("🇦🇪", "ОАЭ"), "RU": ("🇷🇺", "Россия"),
    "KZ": ("🇰🇿", "Казахстан"), "UA": ("🇺🇦", "Украина"), "CZ": ("🇨🇿", "Чехия"),
    "RO": ("🇷🇴", "Румыния"), "BG": ("🇧🇬", "Болгария"), "HU": ("🇭🇺", "Венгрия"),
}

# Кэш данных в памяти бота (на 60 секунд)
_cache_data: Optional[dict] = None
_cache_time: float = 0


# ============================================================
# ПАРСИНГ ДАННЫХ С САЙТА
# ============================================================
async def fetch_site_data(force: bool = False) -> Optional[dict]:
    """Загружает JSON данные с сайта с обработкой кэша."""
    global _cache_data, _cache_time

    now = time.time()
    if not force and _cache_data and (now - _cache_time < 60):
        return _cache_data

    url = f"{SITE_DATA_URL}?t={int(now)}"
    headers = {"User-Agent": "PesokTelegramBot/2.0"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    _cache_data = data
                    _cache_time = now
                    return data
    except Exception as e:
        logging.error(f"Ошибка загрузки с сайта: {e}")

    # Резервная попытка через GitHub Raw
    try:
        fallback_url = f"https://raw.githubusercontent.com/sever-xd/pesok_auto_sub/main/site_data.json?t={int(now)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(fallback_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    _cache_data = data
                    _cache_time = now
                    return data
    except Exception as e:
        logging.error(f"Ошибка загрузки с резервного URL: {e}")

    return _cache_data


def format_ping(ping) -> str:
    """Форматирует пинг с цветным индикатором."""
    if not isinstance(ping, (int, float)) or ping <= 0:
        return "⚪ N/A"
    if ping < 100:
        return f"🟢 {ping} ms"
    elif ping < 300:
        return f"🟡 {ping} ms"
    elif ping < 500:
        return f"🟠 {ping} ms"
    return f"🔴 {ping} ms"


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def get_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚡ Топ-10 по пингу", callback_data="top_servers"),
        InlineKeyboardButton(text="🌍 По странам", callback_data="countries_list"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Ссылка подписки", callback_data="get_sub"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_data"),
    )
    builder.row(
        InlineKeyboardButton(text="🌐 Открыть Веб-Сайт", url=WEBSITE_URL)
    )
    return builder.as_markup()


def get_countries_keyboard(data: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    servers = data.get("servers", [])
    
    # Считаем серверы по странам
    counts = {}
    for s in servers:
        c = s.get("country", "XX")
        counts[c] = counts.get(c, 0) + 1

    # Сортируем популярные
    sorted_countries = sorted(counts.items(), key=lambda x: -x[1])[:18]

    for code, cnt in sorted_countries:
        flag, name = COUNTRY_NAMES.get(code, ("🌐", code))
        builder.button(
            text=f"{flag} {name} ({cnt})",
            callback_data=f"country_{code}"
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")
    )
    return builder.as_markup()


# ============================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================
dp = Dispatcher()


@dp.message(CommandStart())
@dp.message(Command("servers"))
async def cmd_servers(message: types.Message):
    """Главная команда — парсит сайт и выдает актуальные серверы и пинг."""
    wait_msg = await message.answer("🔄 <i>Парсинг актуальных серверов с сайта...</i>", parse_mode=ParseMode.HTML)

    data = await fetch_site_data()
    if not data or not data.get("servers"):
        await wait_msg.edit_text("❌ <b>Не удалось загрузить данные с сайта.</b> Попробуйте позже.")
        return

    servers = data.get("servers", [])
    stats = data.get("stats", {})
    last_update = data.get("last_update", "Неизвестно")

    # Сортируем по пингу (живые первыми)
    sorted_servers = sorted(
        servers,
        key=lambda x: x.get("ping") if isinstance(x.get("ping"), (int, float)) and x.get("ping") > 0 else 99999
    )

    total = len(servers)
    online_count = sum(1 for s in servers if isinstance(s.get("ping"), (int, float)) and s.get("ping") > 0)
    countries_count = len(set(s.get("country") for s in servers))

    text_lines = [
        "🔐 <b>PESOK VPN — АКТУАЛЬНЫЕ СЕРВЕРЫ</b>",
        "<i>create by sever-xd</i>\n",
        f"📊 <b>Статус сети:</b>",
        f"• Всего серверов: <b>{total}</b>",
        f"• Онлайн узлов: <b>{online_count}</b>",
        f"• Доступно стран: <b>{countries_count}</b>",
        f"• Обновлено: <code>{last_update[:19].replace('T', ' ')} UTC</code>\n",
        "⚡ <b>ТОП БЫСТРЫХ СЕРВЕРОВ (МИНИМАЛЬНЫЙ ПИНГ):</b>"
    ]

    # Показываем топ-8 самых быстрых
    for idx, s in enumerate(sorted_servers[:8], 1):
        c_code = s.get("country", "XX")
        flag, c_name = COUNTRY_NAMES.get(c_code, ("🌐", c_code))
        proto = s.get("protocol", "").upper()
        ping_str = format_ping(s.get("ping"))
        remark = s.get("remark", f"[pesok] {flag} {c_name} #{idx:02d}")

        text_lines.append(
            f"{idx}. <b>{remark}</b>\n"
            f"   └ 🔌 <code>{proto}</code> • ⚡ <b>{ping_str}</b> • 📍 <code>{s.get('address')}:{s.get('port')}</code>"
        )

    text_lines.append("\n🔗 <b>Ссылка для подключения (Happ / Hiddify / V2Ray):</b>")
    text_lines.append(f"<code>{SUB_URL}</code>")

    await wait_msg.edit_text(
        "\n".join(text_lines),
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
        disable_web_page_preview=True
    )


@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    """Выводит топ-10 серверов с наименьшим пингом."""
    data = await fetch_site_data()
    if not data or not data.get("servers"):
        await message.answer("❌ <b>Данные недоступны.</b>", parse_mode=ParseMode.HTML)
        return

    servers = sorted(
        data.get("servers", []),
        key=lambda x: x.get("ping") if isinstance(x.get("ping"), (int, float)) and x.get("ping") > 0 else 99999
    )

    lines = ["⚡ <b>ТОП-10 САМЫХ БЫСТРЫХ СЕРВЕРОВ:</b>\n"]
    for i, s in enumerate(servers[:10], 1):
        ping_str = format_ping(s.get("ping"))
        proto = s.get("protocol", "").upper()
        lines.append(f"{i}. <b>{s.get('remark')}</b>\n   └ <code>{proto}</code> | {ping_str} | <code>{s.get('address')}</code>")

    lines.append(f"\n📥 <b>Подписка:</b> <code>{SUB_URL}</code>")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data="get_sub"))
    builder.row(InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu"))

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())


@dp.message(Command("sub"))
async def cmd_sub(message: types.Message):
    """Выдает ссылку на подписку."""
    text = (
        "🔗 <b>ВАША ССЫЛКА НА ПОДПИСКУ PESOK VPN</b>\n\n"
        "Скопируйте и вставьте в <b>Happ</b>, <b>Hiddify</b>, <b>V2RayNG</b>, <b>Clash</b>:\n\n"
        f"<code>{SUB_URL}</code>\n\n"
        "<i>💡 Все сервера будут автоматически названы [pesok] с флагами стран на русском языке.</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌐 Открыть сайт", url=WEBSITE_URL))
    builder.row(InlineKeyboardButton(text="⚡ Показать серверы", callback_data="top_servers"))
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())


# ============================================================
# ОБРАБОТЧИКИ КНОПОК (CALLBACKS)
# ============================================================
@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: types.CallbackQuery):
    data = await fetch_site_data()
    if not data:
        await call.answer("Ошибка загрузки данных", show_alert=True)
        return

    servers = sorted(
        data.get("servers", []),
        key=lambda x: x.get("ping") if isinstance(x.get("ping"), (int, float)) and x.get("ping") > 0 else 99999
    )

    text_lines = [
        "🔐 <b>PESOK VPN — АКТУАЛЬНЫЕ СЕРВЕРЫ</b>",
        "<i>create by sever-xd</i>\n",
        f"• Всего серверов: <b>{len(servers)}</b>",
        f"• Онлайн узлов: <b>{sum(1 for s in servers if isinstance(s.get('ping'), (int, float)) and s.get('ping') > 0)}</b>\n",
        "⚡ <b>ТОП БЫСТРЫХ СЕРВЕРОВ:</b>"
    ]

    for idx, s in enumerate(servers[:8], 1):
        ping_str = format_ping(s.get("ping"))
        text_lines.append(f"{idx}. <b>{s.get('remark')}</b>\n   └ <code>{s.get('protocol', '').upper()}</code> • {ping_str}")

    text_lines.append(f"\n🔗 <b>Подписка:</b> <code>{SUB_URL}</code>")

    await call.message.edit_text(
        "\n".join(text_lines),
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
        disable_web_page_preview=True
    )
    await call.answer()


@dp.callback_query(F.data == "top_servers")
async def cb_top_servers(call: types.CallbackQuery):
    data = await fetch_site_data()
    if not data:
        await call.answer("Ошибка загрузки", show_alert=True)
        return

    servers = sorted(
        data.get("servers", []),
        key=lambda x: x.get("ping") if isinstance(x.get("ping"), (int, float)) and x.get("ping") > 0 else 99999
    )

    lines = ["⚡ <b>ТОП-10 СЕРВЕРОВ С МИНИМАЛЬНЫМ ПИНГОМ:</b>\n"]
    for i, s in enumerate(servers[:10], 1):
        ping_str = format_ping(s.get("ping"))
        lines.append(f"{i}. <b>{s.get('remark')}</b>\n   └ 🔌 <code>{s.get('protocol', '').upper()}</code> • {ping_str} • <code>{s.get('address')}</code>")

    lines.append(f"\n🔗 <b>Подписка:</b> <code>{SUB_URL}</code>")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
    await call.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await call.answer()


@dp.callback_query(F.data == "countries_list")
async def cb_countries_list(call: types.CallbackQuery):
    data = await fetch_site_data()
    if not data:
        await call.answer("Ошибка загрузки", show_alert=True)
        return

    await call.message.edit_text(
        "🌍 <b>Выберите страну для просмотра доступных серверов:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_countries_keyboard(data)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("country_"))
async def cb_country_detail(call: types.CallbackQuery):
    country_code = call.data.split("_")[1]
    data = await fetch_site_data()
    if not data:
        await call.answer("Ошибка данных", show_alert=True)
        return

    c_servers = [s for s in data.get("servers", []) if s.get("country") == country_code]
    flag, name = COUNTRY_NAMES.get(country_code, ("🌐", country_code))

    lines = [f"{flag} <b>СЕРВЕРЫ: {name.upper()} ({len(c_servers)} шт.)</b>\n"]
    for i, s in enumerate(c_servers, 1):
        ping_str = format_ping(s.get("ping"))
        lines.append(
            f"{i}. <b>{s.get('remark')}</b>\n"
            f"   └ 🔌 <code>{s.get('protocol', '').upper()}</code> • ⚡ {ping_str}\n"
            f"   └ 📍 <code>{s.get('address')}:{s.get('port')}</code>"
        )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ К странам", callback_data="countries_list"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    )

    await call.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await call.answer()


@dp.callback_query(F.data == "get_sub")
async def cb_get_sub(call: types.CallbackQuery):
    await call.answer("📋 Ссылка скопирована!", show_alert=False)
    await call.message.answer(
        f"🔗 <b>Ссылка для подключения:</b>\n<code>{SUB_URL}</code>\n\nВставьте ссылку в <b>Happ</b> / <b>Hiddify</b> / <b>V2RayNG</b>.",
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(F.data == "refresh_data")
async def cb_refresh_data(call: types.CallbackQuery):
    await call.answer("🔄 Загрузка свежих данных...", show_alert=False)
    # Принудительно парсим
    data = await fetch_site_data(force=True)
    if data:
        await cb_main_menu(call)
    else:
        await call.answer("❌ Ошибка обновления", show_alert=True)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(message)s"
    )

    if BOT_TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER" or not BOT_TOKEN:
        print("\n" + "=" * 60)
        print("❌ ОШИБКА: Не указан токен бота!")
        print("Получите токен у @BotFather в Telegram и укажите его:")
        print("1. В файле bot.py (переменная BOT_TOKEN)")
        print("2. Или через команду в терминале: set BOT_TOKEN=ваш_токен")
        print("=" * 60 + "\n")
        return

    bot = Bot(token=BOT_TOKEN)
    print("\n🚀 Бот запущен и готов к работе!")
    print(f"📡 Источник данных: {SITE_DATA_URL}\n")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
