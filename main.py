import asyncio
import random
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8540263511:AAGyP8bX_hUoFX_eRdWXHKatiZKi7svZP24")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1003666805503"))
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "7955714952").split(",") if id.strip()]

# Инициализация бота с настройками для Railway
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Список фруктов для капчи
FRUITS = {
    "🍎": "яблоко",
    "🍌": "банан", 
    "🍇": "виноград",
    "🍊": "апельсин",
    "🍓": "клубника",
    "🍑": "персик",
    "🍍": "ананас",
    "🥝": "киви",
    "🍒": "вишня",
    "🍋": "лимон"
}

# Состояния FSM
class CaptchaStates(StatesGroup):
    waiting_for_captcha = State()
    passed = State()

# Хранилище для ожидающих проверки пользователей
pending_users = {}

# Функция для генерации капчи
def generate_captcha():
    correct_fruit_emoji = random.choice(list(FRUITS.keys()))
    correct_fruit_name = FRUITS[correct_fruit_emoji]
    
    all_fruits = list(FRUITS.keys())
    all_fruits.remove(correct_fruit_emoji)
    wrong_fruits = random.sample(all_fruits, 5)
    
    fruits = [correct_fruit_emoji] + wrong_fruits
    random.shuffle(fruits)
    
    return correct_fruit_emoji, correct_fruit_name, fruits

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer(
        "Привет! 👋\n"
        "Этот бот проверяет новых участников для канала.\n"
        "Если ты подал заявку на вступление в канал, "
        "бот автоматически отправит тебе капчу для проверки."
    )

# Обработчик заявок на вступление в канал
@dp.chat_join_request()
async def handle_join_request(update: types.ChatJoinRequest, state: FSMContext):
    user_id = update.from_user.id
    username = update.from_user.username or "без username"
    
    logger.info(f"Новая заявка от пользователя {user_id} (@{username})")
    
    if user_id in pending_users:
        return
    
    correct_emoji, correct_name, fruits = generate_captcha()
    
    pending_users[user_id] = {
        "correct_emoji": correct_emoji,
        "correct_name": correct_name,
        "join_request": update,
        "attempts": 0,
        "timestamp": datetime.now()
    }
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    row = []
    for i, fruit in enumerate(fruits):
        row.append(InlineKeyboardButton(
            text=fruit,
            callback_data=f"captcha_{user_id}_{fruit}"
        ))
        if len(row) == 3 or i == len(fruits) - 1:
            keyboard.inline_keyboard.append(row)
            row = []
    
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"👋 Привет, {update.from_user.first_name}!\n\n"
                 f"Ты подал заявку на вступление в канал. "
                 f"Для подтверждения что ты не бот, пройди простую проверку:\n\n"
                 f"🎯 <b>Выбери фрукт:</b> <code>{correct_name}</code>\n"
                 f"У тебя есть 3 попытки и 5 минут на прохождение капчи.",
            reply_markup=keyboard
        )
        
        await state.set_state(CaptchaStates.waiting_for_captcha)
        logger.info(f"Капча отправлена пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Не удалось отправить капчу пользователю @{username} (ID: {user_id})\n"
                    f"Ошибка: {str(e)}\n"
                    f"Пользователь должен начать диалог с ботом @{(await bot.get_me()).username}"
                )
            except:
                pass

# Обработчик нажатий на кнопки капчи
@dp.callback_query(F.data.startswith("captcha_"))
async def process_captcha(callback: types.CallbackQuery, state: FSMContext):
    _, user_id_str, selected_fruit = callback.data.split("_")
    user_id = int(user_id_str)
    
    if user_id not in pending_users:
        await callback.answer("Время на прохождение капчи истекло! Подай заявку снова.", show_alert=True)
        await callback.message.delete()
        return
    
    user_data = pending_users[user_id]
    
    if datetime.now() - user_data["timestamp"] > timedelta(minutes=5):
        await callback.answer("Время на прохождение капчи истекло! Подай заявку снова.", show_alert=True)
        await callback.message.delete()
        del pending_users[user_id]
        return
    
    user_data["attempts"] += 1
    
    if selected_fruit == user_data["correct_emoji"]:
        try:
            await bot.approve_chat_join_request(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            await callback.message.delete()
            
            await bot.send_message(
                chat_id=user_id,
                text="✅ <b>Поздравляем! Ты прошел проверку!</b>\n\n"
                     "Теперь ты участник канала. Добро пожаловать! 🎉"
            )
            
            await state.set_state(CaptchaStates.passed)
            logger.info(f"Пользователь {user_id} прошел капчу и добавлен в канал")
            
            username = callback.from_user.username or "без username"
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"✅ Пользователь @{username} (ID: {user_id}) прошел капчу и добавлен в канал"
                    )
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя {user_id} в канал: {e}")
            await callback.answer("Произошла ошибка. Свяжись с администратором.", show_alert=True)
        
        del pending_users[user_id]
        
    else:
        attempts_left = 3 - user_data["attempts"]
        
        if attempts_left > 0:
            await callback.answer(
                f"❌ Неправильно! Осталось попыток: {attempts_left}",
                show_alert=True
            )
        else:
            await callback.answer("❌ Попытки закончились! Заявка отклонена.", show_alert=True)
            
            try:
                await bot.decline_chat_join_request(
                    chat_id=CHANNEL_ID,
                    user_id=user_id
                )
                
                await callback.message.delete()
                
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ <b>Заявка отклонена!</b>\n\n"
                         "Ты не прошел проверку. Попробуй подать заявку снова."
                )
                
                logger.info(f"Заявка пользователя {user_id} отклонена")
                
            except Exception as e:
                logger.error(f"Ошибка при отклонении заявки {user_id}: {e}")
            
            del pending_users[user_id]

# Команда для админа
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Ожидают проверки: {len(pending_users)}\n"
        f"🍏 Фруктов в капче: {len(FRUITS)}\n"
        f"🆔 ID канала: {CHANNEL_ID}"
    )
    
    await message.answer(stats_text)

# Главная функция
async def main():
    logger.info("=" * 50)
    logger.info("БОТ ЗАПУЩЕН НА RAILWAY!")
    logger.info(f"Канал ID: {CHANNEL_ID}")
    logger.info(f"Админы: {ADMIN_IDS}")
    logger.info("=" * 50)
    
    # Удаляем вебхук если был установлен
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Уведомляем админов
    bot_info = await bot.get_me()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"✅ Бот @{bot_info.username} запущен на Railway!\n"
                f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except:
            pass
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

