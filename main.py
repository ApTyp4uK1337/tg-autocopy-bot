import os
import json
import asyncio
import logging
from pathlib import Path
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

class TelegramCopyBot:
    def __init__(self, session_name: str):
        self.session_name = session_name
        self.session_path = Path(f"sessions/{session_name}")
        self.session_file = self.session_path / f"{session_name}.session"
        self.config_file = self.session_path / "config.json"
        
        # Создаем папку для сессии если её нет
        self.session_path.mkdir(parents=True, exist_ok=True)
        
        # Получаем API данные из .env
        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        
        if not self.api_id or not self.api_hash:
            raise ValueError("API_ID и API_HASH должны быть установлены в .env файле")
        
        self.client = None
        self.config = {}
        self.is_copying = False
        
    async def load_config(self):
        """Загружаем конфигурацию из файла"""
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            # Создаем конфигурацию по умолчанию
            self.config = {
                "source_channel": "",
                "target_channel": "",
                "delay_seconds": 60
            }
            await self.save_config()
    
    async def save_config(self):
        """Сохраняем конфигурацию в файл"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    async def setup_config(self):
        """Настройка конфигурации при первом запуске"""
        print("\n=== Настройка бота ===")
        
        source = input("Введите ID/username канала-источника (например: @channel_name или -1001234567890): ").strip()
        target = input("Введите ID/username целевого канала (например: @channel_name или -1001234567890): ").strip()
        
        while True:
            try:
                delay = int(input("Введите задержку в секундах между копированием постов (по умолчанию 60): ") or "60")
                break
            except ValueError:
                print("Пожалуйста, введите корректное число")
        
        self.config = {
            "source_channel": source,
            "target_channel": target,
            "delay_seconds": delay
        }
        
        await self.save_config()
        print("✅ Конфигурация сохранена!")
    
    async def authorize(self):
        """Авторизация пользователя"""
        try:
            # Пытаемся подключиться с существующей сессией
            self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
            await self.client.start()
            
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                logger.info(f"Авторизован как: {me.first_name} (@{me.username})")
                return True
            else:
                await self.client.disconnect()
        except:
            pass
        
        # Если не удалось подключиться, запрашиваем новую авторизацию
        print(f"\n=== Авторизация для сессии: {self.session_name} ===")
        
        self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        await self.client.start()
        
        phone = input("Введите номер телефона (с кодом страны, например +7): ").strip()
        
        try:
            await self.client.send_code_request(phone)
            code = input("Введите код из Telegram: ").strip()
            
            try:
                await self.client.sign_in(phone, code)
            except SessionPasswordNeededError:
                password = input("Введите пароль двухфакторной аутентификации: ").strip()
                await self.client.sign_in(password=password)
            
            me = await self.client.get_me()
            logger.info(f"✅ Успешно авторизован как: {me.first_name} (@{me.username})")
            return True
            
        except PhoneCodeInvalidError:
            logger.error("❌ Неверный код подтверждения")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            return False
    
    async def get_entity_info(self, entity_id):
        """Получаем информацию о канале/чате"""
        try:
            entity = await self.client.get_entity(entity_id)
            return entity
        except Exception as e:
            logger.error(f"Не удалось получить информацию о {entity_id}: {e}")
            return None
    
    async def copy_message(self, message):
        """Копируем сообщение в целевой канал"""
        try:
            target_entity = await self.get_entity_info(self.config['target_channel'])
            if not target_entity:
                logger.error("Не удалось получить целевой канал")
                return
            
            # Копируем сообщение
            if message.media:
                # Если есть медиа, пересылаем с медиа
                await self.client.send_message(
                    target_entity,
                    message.message,
                    file=message.media,
                    parse_mode='html'
                )
            else:
                # Если только текст
                await self.client.send_message(
                    target_entity,
                    message.message,
                    parse_mode='html'
                )
            
            logger.info(f"✅ Сообщение скопировано в {self.config['target_channel']}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при копировании сообщения: {e}")
    
    async def start_copying(self):
        """Запускаем мониторинг и копирование постов"""
        if self.is_copying:
            logger.info("Копирование уже запущено")
            return
        
        source_entity = await self.get_entity_info(self.config['source_channel'])
        if not source_entity:
            logger.error("❌ Не удалось получить канал-источник")
            return
        
        target_entity = await self.get_entity_info(self.config['target_channel'])
        if not target_entity:
            logger.error("❌ Не удалось получить целевой канал")
            return
        
        logger.info(f"🚀 Начинаем мониторинг канала: {source_entity.title}")
        logger.info(f"📤 Копируем в канал: {target_entity.title}")
        logger.info(f"⏱️ Задержка: {self.config['delay_seconds']} секунд")
        
        self.is_copying = True
        
        @self.client.on(events.NewMessage(chats=source_entity))
        async def handler(event):
            if not self.is_copying:
                return
                
            logger.info(f"📩 Новое сообщение в канале-источнике")
            
            # Ждем заданную задержку
            if self.config['delay_seconds'] > 0:
                logger.info(f"⏳ Ожидание {self.config['delay_seconds']} секунд...")
                await asyncio.sleep(self.config['delay_seconds'])
            
            # Копируем сообщение
            await self.copy_message(event.message)
        
        logger.info("✅ Мониторинг запущен! Нажмите Ctrl+C для остановки")
        
        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("🛑 Остановка мониторинга...")
            self.is_copying = False
    
    async def run(self):
        """Основной метод запуска бота"""
        try:
            # Загружаем конфигурацию
            await self.load_config()
            
            # Авторизуемся
            if not await self.authorize():
                return
            
            # Если конфигурация пустая, настраиваем
            if not self.config.get('source_channel') or not self.config.get('target_channel'):
                await self.setup_config()
            
            # Показываем текущие настройки
            print(f"\n=== Текущие настройки ===")
            print(f"Канал-источник: {self.config['source_channel']}")
            print(f"Целевой канал: {self.config['target_channel']}")
            print(f"Задержка: {self.config['delay_seconds']} секунд")
            
            # Запускаем копирование
            await self.start_copying()
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
        finally:
            if self.client:
                await self.client.disconnect()

async def main():
    """Главная функция"""
    print("🤖 tg-autocopy-bot")
    print("💎 author: @aptyp4uk1337")
    print("=" * 40)
    
    session_name = input("Введите имя сессии: ").strip()
    if not session_name:
        print("❌ Имя сессии не может быть пустым")
        return
    
    bot = TelegramCopyBot(session_name)
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n💤 Завершение работы")
    except Exception as e:
        print(f"❌ Ошибка: {e}")