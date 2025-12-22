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

RESET_CODE = os.getenv("RESET_CODE")  # /reset КОД (если задан)

EVENT_TITLE = "🎄 Тайный Санта 2025"
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"
COUNTDOWN_SECONDS = 10

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
            "chosen": {},          # user_id(str) -> name(str)
            "pairs": {},           # giver_name -> receiver_name
            "drawn_at": None,
            "draw_in_progress": False,
            "ui": {}               # user_id(str) -> {"chat_id": int, "message_id": int}
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        s = json.load(f)
    s.setdefault("chosen", {})
    s.setdefault("pairs", {})
    s.setdefault("drawn_at", None)
    s.setdefault("draw_in_progress", False)
    s.setdefault("ui", {})
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
        return f"✅ Все готовы: <b>{got}/{total}</b>"
    return f"⏳ Готовность: <b>{got}/{total}</b> (осталось: <b>{left}</b>)"


def panel_text(user_id: int, state: Dict) -> str:
    my = chosen_name_of(user_id, state)
    if state["pairs"]:
        t = (
            f"{header()}\n\n"
            "🎉 <b>Жеребьёвка проведена!</b>\n"
            "Нажми <b>🎁 Моя пара</b>, чтобы увидеть только свою.\n\n"
            "🤫 Пару не раскрываем 🙂\n"
        )
        if my:
            t += f"\n👤 Ты: <b>{my}</b>"
        return t

    t = (
        f"{header()}\n\n"
        "🎅 Правила:\n"
        "1) Выбери, <b>кто ты</b>\n"
        "2) После выбора <b>менять нельзя</b>\n"
        "3) Когда все выберут себя — появится <b>🎲 Жеребьёвка</b>\n\n"
        f"{progress_line(state)}\n"
    )
    if my:
        t += f"\n👤 Ты: <b>{my}</b> ✅"
    else:
        t += "\n👤 Ты ещё не выбран."
    return t


# ================== КНОПКИ ==================
def kb_choose(user_id: int, state: Dict) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)

    for name in PARTICIPANTS:
        mark = " ✅" if name_taken(name, state) else ""
        kb.add(types.InlineKeyboardButton(f"🎁 {name}{mark}", callback_data=f"pick:{name}"))

    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="me"))

    if all_registered(state) and not state["pairs"] and not state["draw_in_progress"]:
        kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="draw"))

    return kb


def kb_after_draw() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🎁 Моя пара", callback_data="my_pair"))
    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="me"))
    return kb


# ================== РЕДАКТИРОВАНИЕ / ОБНОВЛЕНИЕ ==================
def safe_edit_message(chat_id: int, message_id: int, text: str, markup: Optional[types.InlineKeyboardMarkup]) -> bool:
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
        # "message is not modified" — это не ошибка для нас
        if "message is not modified" in str(e).lower():
            return True
        return False
    except Exception:
        return False


def send_or_update_panel(user_id: int) -> None:
    state = load_state()
    ui = state["ui"].get(str(user_id))

    txt = panel_text(user_id, state)
    markup = kb_after_draw() if state["pairs"] else kb_choose(user_id, state)

    if ui:
        ok = safe_edit_message(int(ui["chat_id"]), int(ui["message_id"]), txt, markup)
        if ok:
            return

    # если не было панели или не удалось отредактировать — создаём новую
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


# ================== /start ==================
@bot.message_handler(commands=["start", "help"])
def start(message: types.Message):
    # создаём/обновляем панель пользователю
    send_or_update_panel(message.from_user.id)
    # и обновим всем (на случай, если кто-то только что выбрал/сбросил и т.п.)
    broadcast_refresh()


# ================== /reset ==================
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
    save_state(state)
    broadcast_refresh()


# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    state = load_state()
    uid = call.from_user.id

    if call.data == "me":
        bot.answer_callback_query(call.id, "Ок")
        send_or_update_panel(uid)
        return

    if call.data.startswith("pick:"):
        name = call.data.split(":", 1)[1]

        if state["pairs"]:
            bot.answer_callback_query(call.id, "Жеребьёвка уже была.", show_alert=True)
            return
        if state["draw_in_progress"]:
            bot.answer_callback_query(call.id, "Жеребьёвка запускается.", show_alert=True)
            return

        # запрет смены
        if chosen_name_of(uid, state):
            bot.answer_callback_query(call.id, "Ты уже подтвердил себя. Менять нельзя ✅", show_alert=True)
            return

        # имя занято другим
        if name_taken_by_other(name, uid, state):
            bot.answer_callback_query(call.id, "Это имя уже заняли ✅", show_alert=True)
            return

        # сохраняем выбор
        state["chosen"][str(uid)] = name
        save_state(state)

        bot.answer_callback_query(call.id, f"Готово: {name} ✅")

        # СРАЗУ обновим сообщение, по которому нажали (чтобы галочка появилась моментально)
        state2 = load_state()
        try:
            safe_edit_message(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=panel_text(uid, state2),
                markup=kb_after_draw() if state2["pairs"] else kb_choose(uid, state2)
            )
        except Exception:
            pass

        # и обновим всем остальным
        broadcast_refresh()
        return

    if call.data == "draw":
        if state["pairs"]:
            bot.answer_callback_query(call.id, "Уже проведено.", show_alert=True)
            return
        if state["draw_in_progress"]:
            bot.answer_callback_query(call.id, "Уже запускается.", show_alert=True)
            return
        if not all_registered(state):
            bot.answer_callback_query(call.id, "Ещё не все выбрали себя.", show_alert=True)
            return

        # блокируем
        state["draw_in_progress"] = True
        save_state(state)
        broadcast_refresh()

        bot.answer_callback_query(call.id, "Запускаю 🎲")

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

            # каждому — личное сообщение
            for user_id_str, my_name in state["chosen"].items():
                user_id = int(user_id_str)
                receiver = pairs.get(my_name)
                bot.send_message(
                    user_id,
                    f"{header()}\n\n"
                    "🎁 <b>Твоя пара готова!</b>\n\n"
                    f"Ты даришь: <b>{receiver}</b>\n\n"
                    "🎄 С наступающим! 🤫",
                    reply_markup=kb_after_draw()
                )

            bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="✅ <b>Жеребьёвка проведена!</b>\n\nНажми «🎁 Моя пара».",
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
        if not state["pairs"]:
            bot.answer_callback_query(call.id, "Жеребьёвки ещё не было.", show_alert=True)
            return

        my = chosen_name_of(uid, state)
        if not my:
            bot.answer_callback_query(call.id, "Ты не выбирал себя.", show_alert=True)
            return

        receiver = state["pairs"].get(my)
        bot.answer_callback_query(call.id, "Готово 🎁")
        bot.send_message(
            call.message.chat.id,
            f"{header()}\n\n🎁 <b>Твоя пара</b>\n\nТы даришь: <b>{receiver}</b>\n\n🎄",
            reply_markup=kb_after_draw()
        )
        return

    bot.answer_callback_query(call.id, "Неизвестная кнопка.")


if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
