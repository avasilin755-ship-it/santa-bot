import os
import telebot

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env var is not set")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.send_message(
        message.chat.id,
        "🎅 <b>Тайный Санта</b>\n\n"
        "Бот запущен ✅\n"
        "Дальше добавим создание игры, участие и жеребьёвку."
    )

if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
