import os
import logging
import tempfile
import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range
import matplotlib.pyplot as plt
import io

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из переменной окружения
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

class UserSessionManager:
    """Менеджер сессий пользователей с TTL"""
    
    def __init__(self, ttl_minutes: int = 30):
        self.sessions: Dict[int, Dict[str, Any]] = {}
        self.ttl_seconds = ttl_minutes * 60
        
    def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self.sessions:
            session = self.sessions[user_id]
            if datetime.now() < session.get('expires_at', datetime.min):
                return session
            else:
                del self.sessions[user_id]
        return None
    
    def create_session(self, user_id: int, action: str) -> Dict[str, Any]:
        session = {
            'action': action,
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=self.ttl_seconds)
        }
        self.sessions[user_id] = session
        return session
    
    def clear_expired(self):
        now = datetime.now()
        expired_users = [
            user_id for user_id, session in self.sessions.items()
            if now >= session.get('expires_at', now)
        ]
        for user_id in expired_users:
            del self.sessions[user_id]

class AudioProcessor:
    """Класс для обработки аудио файлов"""
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB в байтах
    
    @staticmethod
    def analyze_audio(audio_segment: AudioSegment) -> Dict[str, float]:
        """Анализ качества аудио"""
        samples = np.array(audio_segment.get_array_of_samples())
        
        # Нормализуем к диапазону -1 до 1
        if audio_segment.sample_width == 2:
            samples = samples / 32768.0
        
        # Базовые метрики
        rms = np.sqrt(np.mean(samples**2))
        peak = np.max(np.abs(samples))
        dynamic_range = 20 * np.log10(peak / (rms + 0.0001))
        quality = min(100, max(0, (dynamic_range / 60) * 100))
        
        return {
            'channels': audio_segment.channels,
            'sample_rate': audio_segment.frame_rate,
            'duration': len(audio_segment) / 1000.0,
            'rms': rms,
            'peak': peak,
            'dynamic_range': dynamic_range,
            'quality': round(quality, 1),
            'is_mono': audio_segment.channels == 1
        }
    
    @staticmethod
    def check_enhanced_tag(file_path: str) -> bool:
        """Проверка, был ли файл уже улучшен"""
        try:
            # Проверяем тег в имени файла
            return '[ENHANCED]' in os.path.basename(file_path)
        except:
            return False
    
    @staticmethod
    def enhance_audio(audio_segment: AudioSegment) -> AudioSegment:
        """Улучшение аудио"""
        # Нормализация
        enhanced = normalize(audio_segment)
        
        # Динамическая компрессия
        enhanced = compress_dynamic_range(enhanced, threshold=-20.0, ratio=4.0, attack=5.0, release=50.0)
        
        # Небольшое усиление
        enhanced = enhanced + 3  # +3 dB
        
        return enhanced
    
    @staticmethod
    def mono_to_stereo(audio_segment: AudioSegment) -> AudioSegment:
        """Конвертация моно в стерео"""
        if audio_segment.channels == 1:
            return AudioSegment.from_mono_audiosegments(audio_segment, audio_segment)
        return audio_segment
    
    @staticmethod
    def create_comparison_chart(before_stats: Dict[str, float], after_stats: Dict[str, float]) -> io.BytesIO:
        """Создание графика сравнения"""
        metrics = ['Качество\n(%)', 'RMS\n(x100)', 'Динамика\n(dB)']
        before_values = [before_stats['quality'], before_stats['rms'] * 100, before_stats['dynamic_range']]
        after_values = [after_stats['quality'], after_stats['rms'] * 100, after_stats['dynamic_range']]
        
        x = np.arange(len(metrics))
        width = 0.35
        
        fig, ax = plt.subplots(figsize=(10, 6))
        bars1 = ax.bar(x - width/2, before_values, width, label='До улучшения', color='#ef4444')
        bars2 = ax.bar(x + width/2, after_values, width, label='После улучшения', color='#10b981')
        
        ax.set_ylabel('Значение', fontsize=12)
        ax.set_title('Сравнение качества аудио', fontsize=14, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(metrics)
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
        
        # Добавляем значения над столбцами
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.1f}',
                       ha='center', va='bottom', fontsize=10)
        
        plt.tight_layout()
        
        # Сохраняем в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        return buf

class AudioBot:
    """Основной класс бота"""
    
    def __init__(self):
        self.session_manager = UserSessionManager()
        self.audio_processor = AudioProcessor()
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        keyboard = [
            [InlineKeyboardButton("📊 Анализ качества", callback_data='analyze')],
            [InlineKeyboardButton("✨ Улучшить звук", callback_data='enhance')],
            [InlineKeyboardButton("🎵 Моно → Стерео", callback_data='mono_to_stereo')],
            [InlineKeyboardButton("🚀 Полная обработка", callback_data='full_process')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "🎵 *Добро пожаловать в Аудио Улучшатель!*\n\n"
            "Я помогу улучшить качество ваших аудио файлов.\n\n"
            "Просто отправьте мне аудио файл и выберите действие:"
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        action = query.data
        
        if action == 'help':
            help_text = (
                "📖 *Инструкция:*\n\n"
                "1️⃣ Отправьте аудио файл\n"
                "2️⃣ Выберите действие:\n\n"
                "📊 *Анализ* - проверка качества звука\n"
                "✨ *Улучшить* - компрессия и усиление\n"
                "🎵 *Моно→Стерео* - конвертация каналов\n"
                "🚀 *Полная обработка* - всё сразу\n\n"
                "Файлы с меткой [ENHANCED] не обрабатываются повторно.\n"
                "Результат сохраняется в формате FLAC."
            )
            await query.edit_message_text(help_text, parse_mode='Markdown')
            return
        
        # Создаем сессию для пользователя
        self.session_manager.create_session(user_id, action)
        
        action_names = {
            'analyze': '📊 Анализ качества',
            'enhance': '✨ Улучшение звука',
            'mono_to_stereo': '🎵 Конвертация в стерео',
            'full_process': '🚀 Полная обработка'
        }
        
        await query.edit_message_text(
            f"Выбрано: *{action_names.get(action, action)}*\n\n"
            f"Теперь отправьте аудио файл для обработки.",
            parse_mode='Markdown'
        )

    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка аудио файлов"""
        user_id = update.message.from_user.id
        
        # Проверяем, есть ли активная сессия
        session = self.session_manager.get_session(user_id)
        if not session:
            await self.send_action_menu(update)
            return
        
        action = session['action']
        
        # Получаем файл
        if update.message.audio:
            file = await update.message.audio.get_file()
            file_name = update.message.audio.file_name or 'audio.mp3'
        elif update.message.voice:
            file = await update.message.voice.get_file()
            file_name = 'voice.ogg'
        elif update.message.document:
            file = await update.message.document.get_file()
            file_name = update.message.document.file_name
        else:
            await update.message.reply_text("❌ Неподдерживаемый тип файла")
            return
        
        # Проверяем размер файла
        if hasattr(file, 'file_size') and file.file_size > self.audio_processor.MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ Размер файла превышает {self.audio_processor.MAX_FILE_SIZE // (1024*1024)} MB")
            return
        
        await update.message.reply_text("⏳ Обрабатываю файл...")
        
        # Используем временный файл
        with tempfile.NamedTemporaryFile(delete=False) as temp_input:
            temp_input_path = temp_input.name
            
        try:
            # Скачиваем файл
            await file.download_to_drive(temp_input_path)
            
            # Проверяем метку
            if self.audio_processor.check_enhanced_tag(temp_input_path):
                await update.message.reply_text("⚠️ Этот файл уже был улучшен ранее!")
                return
            
            # Загружаем аудио
            audio = AudioSegment.from_file(temp_input_path)
            
            # Выполняем выбранное действие
            await self._execute_action(update, action, audio, file_name)
            
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")
        finally:
            # Удаляем временный файл
            if os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
            
            # Удаляем сессию
            if user_id in self.session_manager.sessions:
                del self.session_manager.sessions[user_id]
    
    async def _execute_action(self, update: Update, action: str, audio: AudioSegment, file_name: str):
        """Выполнение выбранного действия"""
        user_id = update.message.from_user.id
        
        if action == 'analyze':
            stats = self.audio_processor.analyze_audio(audio)
            
            analysis_text = (
                f"📊 *Анализ аудио:*\n\n"
                f"🎵 Каналы: {'Моно' if stats['is_mono'] else 'Стерео'}\n"
                f"📡 Частота: {stats['sample_rate']} Hz\n"
                f"⏱ Длительность: {stats['duration']:.1f} сек\n"
                f"📈 Качество: {stats['quality']}%\n"
                f"📊 RMS: {stats['rms']:.3f}\n"
                f"🔊 Peak: {stats['peak']:.3f}\n"
                f"🎚 Динамический диапазон: {stats['dynamic_range']:.1f} dB"
            )
            
            await update.message.reply_text(analysis_text, parse_mode='Markdown')
        
        elif action == 'mono_to_stereo':
            if audio.channels == 1:
                processed_audio = self.audio_processor.mono_to_stereo(audio)
                
                with tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as temp_output:
                    temp_output_path = temp_output.name
                
                try:
                    processed_audio.export(temp_output_path, format='flac')
                    
                    output_filename = file_name.replace('.', '_stereo.') if '.' in file_name else file_name + '_stereo.flac'
                    await update.message.reply_audio(
                        audio=open(temp_output_path, 'rb'),
                        filename=output_filename,
                        caption="✅ Конвертировано в стерео"
                    )
                finally:
                    if os.path.exists(temp_output_path):
                        os.unlink(temp_output_path)
            else:
                await update.message.reply_text("ℹ️ Файл уже в стерео формате")
        
        elif action == 'enhance':
            before_stats = self.audio_processor.analyze_audio(audio)
            processed_audio = self.audio_processor.enhance_audio(audio)
            after_stats = self.audio_processor.analyze_audio(processed_audio)
            
            with tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as temp_output:
                temp_output_path = temp_output.name
            
            try:
                base_name = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
                output_name = f"{base_name}[ENHANCED].flac"
                
                processed_audio.export(temp_output_path, format='flac')
                
                # Отправляем график
                chart = self.audio_processor.create_comparison_chart(before_stats, after_stats)
                await update.message.reply_photo(photo=chart, caption="📊 Сравнение качества")
                
                # Отправляем файл
                await update.message.reply_audio(
                    audio=open(temp_output_path, 'rb'),
                    filename=output_name,
                    caption=(
                        f"✅ *Аудио улучшено!*\n\n"
                        f"Качество: {before_stats['quality']}% → {after_stats['quality']}%"
                    ),
                    parse_mode='Markdown'
                )
            finally:
                if os.path.exists(temp_output_path):
                    os.unlink(temp_output_path)
        
        elif action == 'full_process':
            await update.message.reply_text("🚀 Выполняю полную обработку...")
            
            # Анализ до
            before_stats = self.audio_processor.analyze_audio(audio)
            
            # Моно → Стерео
            if audio.channels == 1:
                audio = self.audio_processor.mono_to_stereo(audio)
                await update.message.reply_text("✓ Конвертировано в стерео")

            # Улучшение
            processed_audio = self.audio_processor.enhance_audio(audio)
            await update.message.reply_text("✓ Звук улучшен")
            
            # Анализ после
            after_stats = self.audio_processor.analyze_audio(processed_audio)
            
            with tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as temp_output:
                temp_output_path = temp_output.name
            
            try:
                base_name = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
                output_name = f"{base_name}[ENHANCED].flac"
                
                processed_audio.export(temp_output_path, format='flac', bitrate='320k')
                
                # График
                chart = self.audio_processor.create_comparison_chart(before_stats, after_stats)
                await update.message.reply_photo(
                    photo=chart,
                    caption="📊 Результаты обработки"
                )
                
                # Итоговый файл
                await update.message.reply_audio(
                    audio=open(temp_output_path, 'rb'),
                    filename=output_name,
                    caption=(
                        f"✅ *Полная обработка завершена!*\n\n"
                        f"📊 Качество: {before_stats['quality']}% → {after_stats['quality']}%\n"
                        f"🎵 Каналы: {'Моно' if before_stats['is_mono'] else 'Стерео'} → Стерео\n"
                        f"💾 Формат: FLAC"
                    ),
                    parse_mode='Markdown'
                )
            finally:
                if os.path.exists(temp_output_path):
                    os.unlink(temp_output_path)
        
        # Показываем меню снова
        await self.send_action_menu(update)

    async def send_action_menu(self, update: Update):
        """Отправка меню выбора действий"""
        keyboard = [
            [InlineKeyboardButton("📊 Анализ", callback_data='analyze'),
             InlineKeyboardButton("✨ Улучшить", callback_data='enhance')],
            [InlineKeyboardButton("🎵 Моно→Стерео", callback_data='mono_to_stereo'),
             InlineKeyboardButton("🚀 Полная обработка", callback_data='full_process')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите действие с аудио:",
            reply_markup=reply_markup
        )

def main():
    """Запуск бота"""
    bot = AudioBot()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, bot.handle_audio))
    
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()