import os
import json
import random
import time
import threading
from typing import Dict, List, Optional

import telebot
from telebot import types

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env var is not set")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

DATA_FILE = "santa_data.json"

# Настройки игры
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"
COUNTDOWN_SECONDS = 10


def load_data() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {"games": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_game(data: Dict, chat_id: int) -> Dict:
    key = str(chat_id)
    if key not in data["games"]:
        data["games"][key] = {
            "participants": {},       # user_id -> info
            "pairs": {},              # giver_user_id -> receiver_user_id
            "drawn_at": None,         # timestamp
            "draw_in_progress": False # блокировка на время таймера/жеребьёвки
        }
    return data["games"][key]


def is_group(chat_type: str) -> bool:
    return chat_type in ("group", "supergroup")


def participants_list(game: Dict) -> List[int]:
    return [int(uid) for uid in game["participants"].keys()]


def build_join_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎁 Участвовать", callback_data="santa_join"))
    kb.add(types.InlineKeyboardButton("👥 Участники", callback_data="santa_list"))
    kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="santa_draw"))
    kb.add(types.InlineKeyboardButton("♻️ Сброс (админы)", callback_data="santa_reset"))
    return kb


def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


@bot.message_handler(commands=["start"])
def start_private(message: types.Message):
    bot.send_message(
        message.chat.id,
        "🎅 <b>Тайный Санта</b>\n\n"
        "Чтобы участвовать — вернись в группу и нажми <b>🎁 Участвовать</b>.\n\n"
        "⚠️ Важно: я смогу прислать тебе пару только если ты уже открыл бота в личке и нажал /start ✅"
    )


@bot.message_handler(commands=["santa"])
def santa_post(message: types.Message):
    if not is_group(message.chat.type):
        bot.send_message(message.chat.id, "Эта команда работает только в группе.")
        return

    text = (
        "🎅 <b>Тайный Санта</b>\n\n"
        f"📅 Дата: <b>{EVENT_DATE}</b>\n"
        f"💰 Бюджет: <b>{BUDGET}</b>\n\n"
        "Нажмите <b>🎁 Участвовать</b>, чтобы войти в игру.\n"
        "Жеребьёвка запускается с таймером <b>10 секунд</b>.\n"
        "Пары <b>никому в группе</b> не показываются — бот пишет каждому <b>в личку</b>.\n\n"
        "⚠️ Если кому-то не приходит личное сообщение — нужно открыть бота и нажать /start."
    )
    bot.send_message(message.chat.id, text, reply_markup=build_join_keyboard())


@bot.message_handler(commands=["draw"])
def draw_cmd(message: types.Message):
    if not is_group(message.chat.type):
        bot.send_message(message.chat.id, "Эта команда работает только в группе.")
        return
    request_draw_with_timer(chat_id=message.chat.id, requested_by=message.from_user.id, message_id=message.message_id)


@bot.message_handler(commands=["reset"])
def reset_cmd(message: types.Message):
    if not is_group(message.chat.type):
        bot.send_message(message.chat.id, "Эта команда работает только в группе.")
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "♻️ Сброс может делать только админ группы.")
        return
    do_reset(message.chat.id, message.from_user.id)


def do_reset(chat_id: int, requested_by: int):
    data = load_data()
    game = ensure_game(data, chat_id)
    game["pairs"] = {}
    game["drawn_at"] = None
    game["draw_in_progress"] = False
    save_data(data)
    bot.send_message(chat_id, "♻️ Игра сброшена. Можно заново собирать участников и запускать жеребьёвку.")


def request_draw_with_timer(chat_id: int, requested_by: int, message_id: Optional[int] = None):
    data = load_data()
    game = ensure_game(data, chat_id)

    if game.get("draw_in_progress"):
        bot.send_message(chat_id, "⏳ Жеребьёвка уже запускается. Подожди немного.")
        return

    if game.get("drawn_at") and game.get("pairs"):
        bot.send_message(chat_id, "🔒 Жеребьёвка уже проведена. Повторно нельзя. (Админ может сделать /reset)")
        return

    users = participants_list(game)
    if len(users) < 3:
        bot.send_message(chat_id, "Нужно минимум 3 участника для жеребьёвки.")
        return

    # ставим блокировку
    game["draw_in_progress"] = True
    save_data(data)

    # сообщение обратного отсчёта
    countdown_msg = bot.send_message(chat_id, f"🎲 Жеребьёвка начнётся через <b>{COUNTDOWN_SECONDS}</b> секунд…")

    # запускаем в отдельном потоке, чтобы бот не “вис”
    t = threading.Thread(
        target=countdown_and_draw,
        args=(chat_id, countdown_msg.message_id),
        daemon=True
    )
    t.start()


def countdown_and_draw(chat_id: int, countdown_message_id: int):
    # обратный отсчёт
    for sec in range(COUNTDOWN_SECONDS, 0, -1):
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=countdown_message_id,
                text=f"🎲 Жеребьёвка начнётся через <b>{sec}</b> секунд…",
                parse_mode="HTML"
            )
        except Exception:
            # если не получилось отредактировать — не критично
            pass
        time.sleep(1)

    # запускаем жеребьёвку
    run_draw(chat_id, countdown_message_id)


def run_draw(chat_id: int, countdown_message_id: int):
    data = load_data()
    game = ensure_game(data, chat_id)

    try:
        users = participants_list(game)
        if len(users) < 3:
            bot.send_message(chat_id, "Недостаточно участников. Жеребьёвка отменена.")
            return

        # генерируем пары без совпадений
        receivers = users[:]
        for _ in range(80):
            random.shuffle(receivers)
            if all(g != r for g, r in zip(users, receivers)):
                break
        else:
            bot.send_message(chat_id, "Не получилось составить пары. Попробуйте ещё раз.")
            return

        pairs = {str(g): int(r) for g, r in zip(users, receivers)}
        game["pairs"] = pairs
        game["drawn_at"] = int(time.time())
        save_data(data)

        sent = 0
        failed = 0

        for giver_str, receiver_id in pairs.items():
            giver_id = int(giver_str)
            receiver_info = game["participants"].get(str(receiver_id), {})
            receiver_name = receiver_info.get("first_name") or receiver_info.get("username") or f"id:{receiver_id}"

            msg = (
                "🎅 <b>Тайный Санта — твоя пара</b>\n\n"
                f"Ты даришь подарок: <b>{receiver_name}</b>\n"
                f"📅 Дата: <b>{EVENT_DATE}</b>\n"
                f"💰 Бюджет: <b>{BUDGET}</b>\n\n"
                "Пожалуйста, не раскрывай пару в чате 🙂"
            )
            try:
                bot.send_message(giver_id, msg)
                sent += 1
            except Exception:
                failed += 1

        # в группе — без раскрытия пар
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=countdown_message_id,
                text=(
                    "🎲 <b>Жеребьёвка проведена!</b>\n"
                    f"✅ Отправлено в личку: <b>{sent}</b>\n"
                    f"⚠️ Не доставлено: <b>{failed}</b>\n\n"
                    "Если кому-то не пришло — нужно открыть бота в личке и нажать /start.\n"
                    "Повторная жеребьёвка заблокирована. (Админ может сделать /reset)"
                ),
                parse_mode="HTML"
            )
        except Exception:
            bot.send_message(
                chat_id,
                f"🎲 Жеребьёвка проведена! В личку отправлено: {sent}, не доставлено: {failed}"
            )

    finally:
        # снимаем блокировку в любом случае
        data = load_data()
        game = ensure_game(data, chat_id)
        game["draw_in_progress"] = False
        save_data(data)


@bot.callback_query_handler(func=lambda call: call.data in ("santa_join", "santa_list", "santa_draw", "santa_reset"))
def santa_callbacks(call: types.CallbackQuery):
    chat = call.message.chat
    user = call.from_user

    if not is_group(chat.type):
        bot.answer_callback_query(call.id, "Это работает только в группе.")
        return

    data = load_data()
    game = ensure_game(data, chat.id)

    if call.data == "santa_join":
        game["participants"][str(user.id)] = {
            "username": user.username,
            "first_name": user.first_name,
            "joined_at": int(time.time())
        }
        save_data(data)
        bot.answer_callback_query(call.id, "Ты участвуешь ✅")
        bot.send_message(chat.id, f"✅ {user.first_name} участвует! Всего: {len(game['participants'])}")

    elif call.data == "santa_list":
        names = []
        for uid_str, info in game["participants"].items():
            n = info.get("first_name") or info.get("username") or f"id:{uid_str}"
            names.append(n)
        if not names:
            bot.answer_callback_query(call.id, "Пока никто не участвует.")
            return
        text = "👥 <b>Участники</b>:\n" + "\n".join(f"• {n}" for n in names)
        bot.answer_callback_query(call.id, "Ок.")
        bot.send_message(chat.id, text)

    elif call.data == "santa_draw":
        bot.answer_callback_query(call.id, "Ок, запускаю…")
        request_draw_with_timer(chat_id=chat.id, requested_by=user.id, message_id=call.message.message_id)

    elif call.data == "santa_reset":
        if not is_admin(chat.id, user.id):
            bot.answer_callback_query(call.id, "Только админ может сбросить.")
            return
        bot.answer_callback_query(call.id, "Сбросил.")
        do_reset(chat.id, user.id)


if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
