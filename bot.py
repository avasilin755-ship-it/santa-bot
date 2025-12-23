import os
import json
import time
import random
from typing import Dict, Optional, List

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# ================== НАСТРОЙКИ ==================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env var is not set")

# Код админа (обязателен). Пример на сервере: export ADMIN_CODE="santa2025"
ADMIN_CODE = os.getenv("ADMIN_CODE")
if not ADMIN_CODE:
    raise RuntimeError("ADMIN_CODE env var is not set")

# Код сброса (необязателен). Пример: export RESET_CODE="reset2025"
RESET_CODE = os.getenv("RESET_CODE")

EVENT_TITLE = "🎄 Тайный Санта 2025"
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"
COUNTDOWN_SECONDS = 10

# Участники (вшито в код)
PARTICIPANTS: List[str] = [
    "Алёна",
    "Ирина",
    "Мария",
    "Марина",
    "Юлия",
]

DATA_FILE = "santa_state.json"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


# ================== ХРАНЕНИЕ ==================
def load_state() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {
            "chosen": {},            # user_id(str) -> name(str)
            "pairs": {},             # giver_name -> receiver_name
            "drawn_at": None,
            "draw_in_progress": False,
            "ui": {},                # user_id(str) -> {"chat_id": int, "message_id": int}
            "admin_id": None,        # int
            "admin_pending": {}      # user_id(str) -> True (ждём код)
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        s = json.load(f)

    s.setdefault("chosen", {})
    s.setdefault("pairs", {})
    s.setdefault("drawn_at", None)
    s.setdefault("draw_in_progress", False)
    s.setdefault("ui", {})
    s.setdefault("admin_id", None)
    s.setdefault("admin_pending", {})
    return s


def save_state(state: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def chosen_name_of(user_id: int, state: Dict) -> Optional[str]:
    return state["chosen"].get(str(user_id))


def name_taken_by_other(name: str, user_id: int, state: Dict) -> bool:
    for uid_str, nm in state["chosen"].items():
        if nm == name and uid_str != str(user_id):
            return True
    return False


def name_taken(name: str, state: Dict) -> bool:
    return name in state["chosen"].values()


def all_registered(state: Dict) -> bool:
    return len(set(state["chosen"].values())) == len(PARTICIPANTS)


def is_admin(user_id: int, state: Dict) -> bool:
    return state.get("admin_id") == user_id


# ================== ТЕКСТЫ ==================
def header() -> str:
    return (
        f"❄️ <b>{EVENT_TITLE}</b> ❄️\n"
        f"📅 Дата: <b>{EVENT_DATE}</b>\n"
        f"💰 Лимит: <b>{BUDGET}</b>\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def progress_line(state: Dict) -> str:
    got = len(set(state["chosen"].values()))
    total = len(PARTICIPANTS)
    left = total - got
    if left <= 0:
        return f"✅ Все участники готовы: <b>{got}/{total}</b>"
    return f"⏳ Готовность: <b>{got}/{total}</b> (осталось: <b>{left}</b>)"


def panel_text(user_id: int, state: Dict) -> str:
    my = chosen_name_of(user_id, state)
    admin_mark = "✅" if is_admin(user_id, state) else "❌"

    if state["pairs"]:
        t = (
            f"{header()}\n\n"
            "🎉 <b>Жеребьёвка проведена!</b>\n"
            "Нажми <b>🎁 Моя пара</b>, чтобы увидеть только свою.\n\n"
            f"👑 Администратор: <b>{admin_mark}</b>\n"
            "🤫 Пару не раскрываем 🙂\n"
        )
        if is_admin(user_id, state):
            t += "\n\n👑 Ты администратор. Пара тебе не выдаётся."
        elif my:
            t += f"\n\n👤 Ты: <b>{my}</b>"
        else:
            t += "\n\n⚠️ Ты не выбрал себя до жеребьёвки."
        return t

    t = (
        f"{header()}\n\n"
        "🎅 Как это работает:\n"
        "1) Участники выбирают, <b>кто они</b>\n"
        "2) После выбора <b>менять нельзя</b>\n"
        "3) Админ подтверждается кнопкой <b>👑 Администратор</b>\n"
        "4) Когда все готовы — админ запускает <b>🎲 Жеребьёвку</b>\n\n"
        f"{progress_line(state)}\n"
        f"👑 Администратор: <b>{admin_mark}</b>\n"
    )
    if is_admin(user_id, state):
        t += "\n👑 Ты админ. Ты не участвуешь в жеребьёвке, пары тебе не будет."
    elif my:
        t += f"\n👤 Ты: <b>{my}</b> ✅"
    else:
        t += "\n👤 Ты ещё не выбран."
    return t


# ================== КНОПКИ ==================
def kb_choose(user_id: int, state: Dict) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)

    # участники выбирают себя
    for name in PARTICIPANTS:
        mark = " ✅" if name_taken(name, state) else ""
        kb.add(types.InlineKeyboardButton(f"🎁 {name}{mark}", callback_data=f"pick:{name}"))

    # 👑 кнопка администратора исчезает после подтверждения
    if state.get("admin_id") is None:
        kb.add(types.InlineKeyboardButton("👑 Администратор", callback_data="admin"))

    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="me"))

    # 🎲 появляется ТОЛЬКО у админа, только когда все готовы
    if is_admin(user_id, state) and all_registered(state) and not state["pairs"] and not state["draw_in_progress"]:
        kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="draw"))

    return kb


def kb_after_draw(user_id: int, state: Dict) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    if not is_admin(user_id, state):
        kb.add(types.InlineKeyboardButton("🎁 Моя пара", callback_data="my_pair"))
    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="me"))
    return kb


# ================== ОБНОВЛЕНИЕ ПАНЕЛЕЙ ==================
def safe_edit_message(chat_id: int, message_id: int, text: str,
                      markup: Optional[types.InlineKeyboardMarkup]) -> bool:
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup
        )
        return True
    except ApiTelegramException as e:
        if "message is not modified" in str(e).lower():
            return True
        return False
    except Exception:
        return False


def send_or_update_panel(user_id: int) -> None:
    state = load_state()
    ui = state["ui"].get(str(user_id))

    txt = panel_text(user_id, state)
    markup = kb_after_draw(user_id, state) if state["pairs"] else kb_choose(user_id, state)

    if ui:
        ok = safe_edit_message(int(ui["chat_id"]), int(ui["message_id"]), txt, markup)
        if ok:
            return

    sent = bot.send_message(user_id, txt, reply_markup=markup)
    state = load_state()
    state["ui"][str(user_id)] = {"chat_id": sent.chat.id, "message_id": sent.message_id}
    save_state(state)


def broadcast_refresh() -> None:
    state = load_state()
    dead = []
    for uid_str in list(state["ui"].keys()):
        uid = int(uid_str)
        try:
            send_or_update_panel(uid)
        except Exception:
            dead.append(uid_str)
        time.sleep(0.1)

    if dead:
        state = load_state()
        for k in dead:
            state["ui"].pop(k, None)
        save_state(state)


# ================== ЖЕРЕБЬЁВКА ==================
def build_pairs(names: List[str]) -> Dict[str, str]:
    receivers = names[:]
    for _ in range(200):
        random.shuffle(receivers)
        if all(g != r for g, r in zip(names, receivers)):
            return {g: r for g, r in zip(names, receivers)}
    raise RuntimeError("Не удалось составить пары.")


# ================== КОМАНДЫ ==================
@bot.message_handler(commands=["start", "help"])
def start(message: types.Message):
    send_or_update_panel(message.from_user.id)
    broadcast_refresh()


@bot.message_handler(commands=["myid"])
def myid(message: types.Message):
    bot.send_message(message.chat.id, f"🆔 Твой ID: <code>{message.from_user.id}</code>")


@bot.message_handler(commands=["reset"])
def reset(message: types.Message):
    if not RESET_CODE:
        bot.send_message(message.chat.id, "♻️ Сброс отключён (нет RESET_CODE на сервере).")
        return
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2 or parts[1] != RESET_CODE:
        bot.send_message(message.chat.id, "Формат: <code>/reset КОД</code>")
        return

    state = load_state()
    state["chosen"] = {}
    state["pairs"] = {}
    state["drawn_at"] = None
    state["draw_in_progress"] = False
    state["admin_id"] = None
    state["admin_pending"] = {}
    save_state(state)
    broadcast_refresh()


# Если кто-то нажал "Администратор", ждём, что он пришлёт код обычным сообщением
@bot.message_handler(func=lambda m: True, content_types=["text"])
def catch_admin_code(message: types.Message):
    state = load_state()
    uid_str = str(message.from_user.id)

    if not state["admin_pending"].get(uid_str):
        return  # обычные сообщения игнорируем

    code = (message.text or "").strip()
    if code != ADMIN_CODE:
        bot.send_message(message.chat.id, "❌ Неверный код. Попробуй ещё раз.")
        return

    # назначаем админа
    state["admin_id"] = message.from_user.id
    state["admin_pending"].pop(uid_str, None)
    save_state(state)

    bot.send_message(message.chat.id, "👑 Готово! Ты подтверждён как администратор ✅")
    broadcast_refresh()


# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    state = load_state()
    uid = call.from_user.id

    def answer(text: str, alert: bool = False):
        try:
            bot.answer_callback_query(call.id, text, show_alert=alert)
        except Exception:
            pass

    if call.data == "me":
        answer("Ок")
        send_or_update_panel(uid)
        return

    if call.data == "admin":
        # если админ уже назначен — просто скажем
        if state.get("admin_id") is not None:
            answer("Администратор уже подтверждён.", alert=True)
            return

        state["admin_pending"][str(uid)] = True
        save_state(state)
        answer("Введи код администратора в чат")
        bot.send_message(call.message.chat.id, "🔐 Введи <b>код администратора</b> следующим сообщением.")
        return

    if call.data.startswith("pick:"):
        name = call.data.split(":", 1)[1]

        if state["pairs"]:
            answer("Жеребьёвка уже была.", alert=True)
            return
        if state["draw_in_progress"]:
            answer("Жеребьёвка запускается.", alert=True)
            return

        # админ не участвует
        if is_admin(uid, state):
            answer("Администратор не участвует в выборе имени.", alert=True)
            return

        # запрет смены
        if chosen_name_of(uid, state):
            answer("Ты уже подтвердил себя. Менять нельзя ✅", alert=True)
            return

        if name_taken_by_other(name, uid, state):
            answer("Это имя уже заняли ✅", alert=True)
            return

        state["chosen"][str(uid)] = name
        save_state(state)
        answer(f"Готово: {name} ✅")

        broadcast_refresh()
        return

    if call.data == "draw":
        # только админ
        if not is_admin(uid, state):
            answer("Жеребьёвку запускает только админ 👑", alert=True)
            return

        if state["pairs"]:
            answer("Уже проведено.", alert=True)
            return
        if state["draw_in_progress"]:
            answer("Уже запускается.", alert=True)
            return
        if not all_registered(state):
            answer("Ещё не все участники выбрали себя.", alert=True)
            return

        state["draw_in_progress"] = True
        save_state(state)
        broadcast_refresh()
        answer("Запускаю 🎲")

        msg = bot.send_message(call.message.chat.id, f"🎄 Жеребьёвка через <b>{COUNTDOWN_SECONDS}</b>…")
        for s in range(COUNTDOWN_SECONDS, 0, -1):
            try:
                bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=msg.message_id,
                    text=f"🎄 <b>Жеребьёвка</b> через <b>{s}</b>… ❄️",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            time.sleep(1)

        try:
            pairs = build_pairs(PARTICIPANTS[:])
            state = load_state()
            state["pairs"] = pairs
            state["drawn_at"] = int(time.time())
            save_state(state)

            # рассылаем всем участникам (кроме админа)
            admin_id = state.get("admin_id")
            for user_id_str, my_name in state["chosen"].items():
                user_id = int(user_id_str)
                if admin_id and user_id == admin_id:
                    continue
                receiver = pairs.get(my_name)
                bot.send_message(
                    user_id,
                    f"{header()}\n\n"
                    "🎁 <b>Твоя пара готова!</b>\n\n"
                    f"Ты даришь: <b>{receiver}</b>\n\n"
                    "🎄 С наступающим! 🤫",
                    reply_markup=kb_after_draw(user_id, state)
                )

            bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="✅ <b>Жеребьёвка проведена!</b>\n\nПары разосланы участникам 🎁",
                parse_mode="HTML"
            )
        finally:
            state = load_state()
            state["draw_in_progress"] = False
            save_state(state)
            broadcast_refresh()

        return

    if call.data == "my_pair":
        state = load_state()
        if is_admin(uid, state):
            answer("Админу пара не выдаётся 👑", alert=True)
            return
        if not state["pairs"]:
            answer("Жеребьёвки ещё не было.", alert=True)
            return

        my = chosen_name_of(uid, state)
        if not my:
            answer("Ты не выбирал себя.", alert=True)
            return

        receiver = state["pairs"].get(my)
        answer("Готово 🎁")
        bot.send_message(
            call.message.chat.id,
            f"{header()}\n\n"
            f"🎁 <b>Твоя пара</b>\n\nТы даришь: <b>{receiver}</b>\n\n🎄",
            reply_markup=kb_after_draw(uid, state)
        )
        return

    answer("Неизвестная кнопка.")


if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
