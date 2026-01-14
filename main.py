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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# Проверка конфигурации
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения")
if not CHANNEL_ID:
    raise ValueError("CHANNEL_ID не установлен в переменных окружения")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не установлен в переменных окружения")

logger.info(f"Бот инициализирован для канала ID: {CHANNEL_ID}")
logger.info(f"Администраторы: {ADMIN_IDS}")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
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
    # Выбираем случайный фрукт как правильный ответ
    correct_fruit_emoji = random.choice(list(FRUITS.keys()))
    correct_fruit_name = FRUITS[correct_fruit_emoji]
    
    # Выбираем 6 случайных фруктов (включая правильный)
    all_fruits = list(FRUITS.keys())
    all_fruits.remove(correct_fruit_emoji)
    wrong_fruits = random.sample(all_fruits, 5)
    
    # Создаем список из 6 фруктов и перемешиваем
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
    
    # Проверяем, не обрабатывается ли уже этот пользователь
    if user_id in pending_users:
        return
    
    # Генерируем капчу
    correct_emoji, correct_name, fruits = generate_captcha()
    
    # Сохраняем данные для проверки
    pending_users[user_id] = {
        "correct_emoji": correct_emoji,
        "correct_name": correct_name,
        "join_request": update,
        "attempts": 0,
        "timestamp": datetime.now()
    }
    
    # Создаем клавиатуру с фруктами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Добавляем фрукты в 2 ряда по 3
    row = []
    for i, fruit in enumerate(fruits):
        row.append(InlineKeyboardButton(
            text=fruit,
            callback_data=f"captcha_{user_id}_{fruit}"
        ))
        if len(row) == 3 or i == len(fruits) - 1:
            keyboard.inline_keyboard.append(row)
            row = []
    
    # Отправляем сообщение с капчей
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"👋 Привет, {update.from_user.first_name}!\n\n"
                 f"Ты подал заявку на вступление в канал. "
                 f"Для подтверждения что ты не бот, пройди простую проверку:\n\n"
                 f"🎯 <b>Выбери фрукт:</b> <code>{correct_name}</code>\n"
                 f"У тебя есть 3 попытки и 5 минут на прохождение капчи.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Устанавливаем состояние ожидания капчи
        await state.set_state(CaptchaStates.waiting_for_captcha)
        
        logger.info(f"Капча отправлена пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        
        # Уведомляем админа
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
    # Парсим данные из callback_data
    _, user_id_str, selected_fruit = callback.data.split("_")
    user_id = int(user_id_str)
    
    # Проверяем, существует ли запись об этом пользователе
    if user_id not in pending_users:
        await callback.answer("Время на прохождение капчи истекло! Подай заявку снова.", show_alert=True)
        await callback.message.delete()
        return
    
    user_data = pending_users[user_id]
    
    # Проверяем время (5 минут)
    if datetime.now() - user_data["timestamp"] > timedelta(minutes=5):
        await callback.answer("Время на прохождение капчи истекло! Подай заявку снова.", show_alert=True)
        await callback.message.delete()
        del pending_users[user_id]
        return
    
    # Увеличиваем счетчик попыток
    user_data["attempts"] += 1
    
    # Проверяем ответ
    if selected_fruit == user_data["correct_emoji"]:
        # Правильный ответ
        try:
            # Одобряем заявку
            await bot.approve_chat_join_request(
                chat_id=CHANNEL_ID,
                user_id=user_id
            )
            
            # Удаляем сообщение с капчей
            await callback.message.delete()
            
            # Отправляем сообщение об успехе
            await bot.send_message(
                chat_id=user_id,
                text="✅ <b>Поздравляем! Ты прошел проверку!</b>\n\n"
                     "Теперь ты участник канала. Добро пожаловать! 🎉",
                parse_mode="HTML"
            )
            
            # Устанавливаем состояние "прошел"
            await state.set_state(CaptchaStates.passed)
            
            logger.info(f"Пользователь {user_id} прошел капчу и добавлен в канал")
            
            # Уведомляем админа
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
        
        # Удаляем пользователя из ожидания
        del pending_users[user_id]
        
    else:
        # Неправильный ответ
        attempts_left = 3 - user_data["attempts"]
        
        if attempts_left > 0:
            # Есть еще попытки
            await callback.answer(
                f"❌ Неправильно! Осталось попыток: {attempts_left}",
                show_alert=True
            )
        else:
            # Попытки закончились
            await callback.answer("❌ Попытки закончились! Заявка отклонена.", show_alert=True)
            
            try:
                # Отклоняем заявку
                await bot.decline_chat_join_request(
                    chat_id=CHANNEL_ID,
                    user_id=user_id
                )
                
                # Удаляем сообщение с капчей
                await callback.message.delete()
                
                # Отправляем сообщение об отклонении
                await bot.send_message(
                    chat_id=user_id,
                    text="❌ <b>Заявка отклонена!</b>\n\n"
                         "Ты не прошел проверку. Попробуй подать заявку снова.",
                    parse_mode="HTML"
                )
                
                logger.info(f"Заявка пользователя {user_id} отклонена")
                
            except Exception as e:
                logger.error(f"Ошибка при отклонении заявки {user_id}: {e}")
            
            # Удаляем пользователя из ожидания
            del pending_users[user_id]

# Команда для админа: статистика
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Ожидают проверки: {len(pending_users)}\n"
        f"🍏 Фруктов в капче: {len(FRUITS)}\n"
        f"🆔 ID канала: {CHANNEL_ID}\n"
        f"🤖 Юзернейм бота: @{(await bot.get_me()).username}\n"
        f"⏰ Время работы: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await message.answer(stats_text, parse_mode="HTML")

# Команда для админа: очистка ожидания
@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    cleared = len(pending_users)
    pending_users.clear()
    
    await message.answer(f"✅ Очищено {cleared} пользователей из ожидания")

# Команда для админа: список ожидающих
@dp.message(Command("pending"))
async def cmd_pending(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    if not pending_users:
        await message.answer("📭 Список ожидающих пуст.")
        return
    
    pending_list = "📋 <b>Ожидающие проверку:</b>\n\n"
    for user_id, data in pending_users.items():
        time_passed = datetime.now() - data["timestamp"]
        minutes_left = 5 - int(time_passed.total_seconds() / 60)
        minutes_left = max(0, minutes_left)
        
        pending_list += f"👤 ID: {user_id}\n"
        pending_list += f"   🎯 Фрукт: {data['correct_name']}\n"
        pending_list += f"   🔄 Попытки: {data['attempts']}/3\n"
        pending_list += f"   ⏱ Осталось: {minutes_left} мин\n\n"
    
    await message.answer(pending_list, parse_mode="HTML")

# Команда для админа: перезагрузка
@dp.message(Command("restart"))
async def cmd_restart(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await message.answer("🔄 Перезагрузка бота...")
    logger.info("Перезагрузка бота по команде администратора")
    # На Railway перезагрузка происходит автоматически при деплое

# Функция очистки устаревших записей
async def cleanup_pending_users():
    while True:
        await asyncio.sleep(60)  # Проверка каждую минуту
        
        now = datetime.now()
        expired_users = []
        
        for user_id, data in pending_users.items():
            if now - data["timestamp"] > timedelta(minutes=5):
                expired_users.append(user_id)
        
        for user_id in expired_users:
            try:
                # Отклоняем просроченные заявки
                await bot.decline_chat_join_request(
                    chat_id=CHANNEL_ID,
                    user_id=user_id
                )
                
                # Пытаемся уведомить пользователя
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="⏰ Время на прохождение капчи истекло.\n"
                             "Подай заявку снова, если хочешь присоединиться к каналу."
                    )
                except:
                    pass
                
            except Exception as e:
                logger.error(f"Ошибка при очистке пользователя {user_id}: {e}")
            
            # Удаляем из pending_users
            if user_id in pending_users:
                del pending_users[user_id]
        
        if expired_users:
            logger.info(f"Очищено {len(expired_users)} просроченных заявок")

# Команда для проверки работоспособности
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    await message.answer(
        f"✅ Бот работает!\n"
        f"🤖 Юзернейм: @{(await bot.get_me()).username}\n"
        f"🕐 Время сервера: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

# Обработчик любых сообщений
@dp.message()
async def handle_any_message(message: types.Message):
    # Игнорируем сообщения от ботов
    if message.from_user.is_bot:
        return
    
    # Отвечаем на простые сообщения
    if message.text:
        await message.answer(
            "Я бот для проверки заявок в канал. "
            "Используй /start для получения информации."
        )

# Главная функция запуска
async def main():
    logger.info("=" * 50)
    logger.info("Запуск Telegram Captcha Bot")
    logger.info("=" * 50)
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    logger.info(f"Бот: @{bot_info.username} ({bot_info.id})")
    logger.info(f"Канал ID: {CHANNEL_ID}")
    logger.info(f"Администраторы: {ADMIN_IDS}")
    
    # Запускаем фоновую задачу очистки
    asyncio.create_task(cleanup_pending_users())
    
    # Уведомляем админов о запуске
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"✅ Бот @{bot_info.username} запущен!\n"
                f"🕐 Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📊 Используй /stats для статистики"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить администратора {admin_id}: {e}")
    
    # Удаляем вебхук если есть (для чистого запуска)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем поллинг
    logger.info("Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
