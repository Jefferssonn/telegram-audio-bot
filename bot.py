import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range
import matplotlib.pyplot as plt
import io

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота из переменной окружения
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# Хранилище для состояния пользователей
user_data = {}

class AudioProcessor:
    @staticmethod
    def analyze_audio(audio_segment):
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
    def check_enhanced_tag(file_path):
        """Проверка, был ли файл уже улучшен"""
        try:
            audio = AudioSegment.from_file(file_path)
            # Проверяем тег в метаданных (упрощенная версия)
            return '[ENHANCED]' in os.path.basename(file_path)
        except:
            return False
    
    @staticmethod
    def enhance_audio(audio_segment):
        """Улучшение аудио"""
        # Нормализация
        enhanced = normalize(audio_segment)
        
        # Динамическая компрессия
        enhanced = compress_dynamic_range(enhanced, threshold=-20.0, ratio=4.0, attack=5.0, release=50.0)
        
        # Небольшое усиление
        enhanced = enhanced + 3  # +3 dB
        
        return enhanced
    
    @staticmethod
    def mono_to_stereo(audio_segment):
        """Конвертация моно в стерео"""
        if audio_segment.channels == 1:
            return AudioSegment.from_mono_audiosegments(audio_segment, audio_segment)
        return audio_segment
    
    @staticmethod
    def create_comparison_chart(before_stats, after_stats):
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # Сохраняем выбранное действие
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['action'] = action
    
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

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка аудио файлов"""
    user_id = update.message.from_user.id
    
    # Проверяем, выбрано ли действие
    if user_id not in user_data or 'action' not in user_data[user_id]:
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
        return
    
    action = user_data[user_id]['action']
    
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
    
    await update.message.reply_text("⏳ Обрабатываю файл...")
    
    try:
        # Скачиваем файл
        input_path = f'temp_{user_id}_input'
        await file.download_to_drive(input_path)
        
        # Проверяем метку
        if AudioProcessor.check_enhanced_tag(input_path):
            await update.message.reply_text("⚠️ Этот файл уже был улучшен ранее!")
            os.remove(input_path)
            return
        
        # Загружаем аудио
        audio = AudioSegment.from_file(input_path)
        
        # Выполняем выбранное действие
        if action == 'analyze':
            stats = AudioProcessor.analyze_audio(audio)
            
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
                audio = AudioProcessor.mono_to_stereo(audio)
                output_path = f'temp_{user_id}_output.flac'
                audio.export(output_path, format='flac')
                
                await update.message.reply_audio(
                    audio=open(output_path, 'rb'),
                    filename=file_name.replace('.', '_stereo.') if '.' in file_name else file_name + '_stereo.flac',
                    caption="✅ Конвертировано в стерео"
                )
                os.remove(output_path)
            else:
                await update.message.reply_text("ℹ️ Файл уже в стерео формате")
        
        elif action == 'enhance':
            before_stats = AudioProcessor.analyze_audio(audio)
            enhanced = AudioProcessor.enhance_audio(audio)
            after_stats = AudioProcessor.analyze_audio(enhanced)
            
            output_path = f'temp_{user_id}_output.flac'
            base_name = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
            output_name = f"{base_name}[ENHANCED].flac"
            
            enhanced.export(output_path, format='flac')
            
            # Отправляем график
            chart = AudioProcessor.create_comparison_chart(before_stats, after_stats)
            await update.message.reply_photo(photo=chart, caption="📊 Сравнение качества")
            
            # Отправляем файл
            await update.message.reply_audio(
                audio=open(output_path, 'rb'),
                filename=output_name,
                caption=(
                    f"✅ *Аудио улучшено!*\n\n"
                    f"Качество: {before_stats['quality']}% → {after_stats['quality']}%"
                ),
                parse_mode='Markdown'
            )
            os.remove(output_path)
        
        elif action == 'full_process':
            await update.message.reply_text("🚀 Выполняю полную обработку...")
            
            # Анализ до
            before_stats = AudioProcessor.analyze_audio(audio)
            
            # Моно → Стерео
            if audio.channels == 1:
                audio = AudioProcessor.mono_to_stereo(audio)
                await update.message.reply_text("✓ Конвертировано в стерео")
            
            # Улучшение
            enhanced = AudioProcessor.enhance_audio(audio)
            await update.message.reply_text("✓ Звук улучшен")
            
            # Анализ после
            after_stats = AudioProcessor.analyze_audio(enhanced)
            
            # Сохранение
            output_path = f'temp_{user_id}_output.flac'
            base_name = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
            output_name = f"{base_name}[ENHANCED].flac"
            
            enhanced.export(output_path, format='flac', bitrate='320k')
            
            # График
            chart = AudioProcessor.create_comparison_chart(before_stats, after_stats)
            await update.message.reply_photo(
                photo=chart,
                caption="📊 Результаты обработки"
            )
            
            # Итоговый файл
            await update.message.reply_audio(
                audio=open(output_path, 'rb'),
                filename=output_name,
                caption=(
                    f"✅ *Полная обработка завершена!*\n\n"
                    f"📊 Качество: {before_stats['quality']}% → {after_stats['quality']}%\n"
                    f"🎵 Каналы: {'Моно' if before_stats['is_mono'] else 'Стерео'} → Стерео\n"
                    f"💾 Формат: FLAC"
                ),
                parse_mode='Markdown'
            )
            os.remove(output_path)
        
        # Очистка
        os.remove(input_path)
        
        # Показываем меню снова
        keyboard = [
            [InlineKeyboardButton("📊 Анализ", callback_data='analyze'),
             InlineKeyboardButton("✨ Улучшить", callback_data='enhance')],
            [InlineKeyboardButton("🎵 Моно→Стерео", callback_data='mono_to_stereo'),
             InlineKeyboardButton("🚀 Полная обработка", callback_data='full_process')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Обработать ещё один файл?",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")
        if os.path.exists(input_path):
            os.remove(input_path)

def main():
    """Запуск бота"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.AUDIO, handle_audio))
    
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
