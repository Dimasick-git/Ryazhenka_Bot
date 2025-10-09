<div align="center">

# 🎮 Ryazhenka Helper Bot

### *Your Ultimate Nintendo Switch Modding Guide Assistant*

[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue?style=for-the-badge&logo=telegram)](https://telegram.org/)
[![Python](https://img.shields.io/badge/Python-3.9+-green?style=for-the-badge&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

*Автоматизированный Telegram-бот для поиска, синхронизации и управления гайдами по моддингу Nintendo Switch*

[Features](#-возможности) • [Quick Start](#-быстрый-старт) • [Commands](#-команды) • [Deploy](#-деплой-на-railway) • [Security](#-безопасность)

</div>

---

## 📖 Описание

**Ryazhenka Helper Bot** — это интеллектуальный Telegram-бот, созданный для энтузиастов моддинга Nintendo Switch. Бот автоматически собирает, структурирует и предоставляет доступ к проверенным гайдам из YouTube и GitHub, делая процесс поиска информации максимально простым и удобным.

### 🎯 Для кого этот бот?

- 🔧 Разработчиков homebrew-приложений для Switch
- 🎮 Энтузиастов кастомной прошивки и моддинга
- 📚 Сообществ, нуждающихся в централизованной базе знаний
- 🤖 Тех, кто ценит автоматизацию и структурированную информацию

---

## ✨ Возможности

<table>
<tr>
<td width="50%">

### 🔍 Умный поиск
- **Fuzzy-поиск** с использованием `fuzzywuzzy`
- Поддержка опечаток и неточных запросов
- Мгновенные результаты по ключевым словам
- Поиск на русском и английском языках

### 🔄 Автоматическая синхронизация
- **YouTube RSS** — новые видео-гайды
- **GitHub Releases** — обновления через Atom
- **Периодическая проверка** — каждые 30 минут
- **Smart-кэширование** для оптимизации

</td>
<td width="50%">

### 🤖 Telegram интеграция
- **Inline-кнопки** для навигации
- **Rich-форматирование** сообщений
- **Прямые ссылки** на гайды
- **Admin-панель** для управления

### 🔒 Безопасность
- **Whitelist-система** для доменов
- **Role-based** управление доступом
- **Логирование** всех действий
- **Rate limiting** для защиты

</td>
</tr>
</table>

---

## 🚀 Быстрый старт

### Шаг 1: Клонирование репозитория

```bash
git clone https://github.com/Dimasick-git/Ryazhenka_Bot.git
cd Ryazhenka_Bot
```

### Шаг 2: Установка зависимостей

```bash
pip install -r requirements.txt
```

### Шаг 3: Настройка переменных

Скопируйте `.env.example` в `.env` и заполните значения:

| Переменная | Описание | Пример |
|------------|----------|--------|
| `BOT_TOKEN` | Telegram Bot API токен от [@BotFather](https://t.me/BotFather) | `1234567890:ABC...` |
| `ADMIN_IDS` | Список Telegram ID администраторов (через запятую) | `123456789,987654321` |
| `ALLOWED_DOMAINS` | Whitelist доменов для безопасности | `youtube.com,github.com` |
| `PORT` | Порт для веб-сервера (для Railway) | `8080` |

#### 📺 YouTube Channels

**Настройка каналов YouTube:**

Для мониторинга YouTube каналов используйте переменную `YT_CHANNELS` в файле `.env`. 

**Важно:** Рекомендуется указывать полную ссылку на канал, а не handle.

**Пример конфигурации:**
```bash
YT_CHANNELS=https://www.youtube.com/@Chipovshchik
```

**Для нескольких каналов разделяйте запятой:**
```bash
YT_CHANNELS=https://www.youtube.com/@Chipovshchik,https://www.youtube.com/@AnotherChannel
```

**Почему URL, а не handle:**
- ✅ Более надёжное определение канала
- ✅ Избегает конфликтов с похожими handle
- ✅ Работает со всеми типами URL каналов

Однако теперь вы можете управлять каналами прямо из бота — вам не нужно править `.env` вручную.

Админские команды для работы с YouTube каналами:

- `/yt_add <url_or_handle_or_UC>` — добавить канал в мониторинг
- `/yt_remove <url_or_handle_or_UC>` — удалить канал
- `/yt_list` — показать текущие отслеживаемые каналы
- `/yt_cache` — показать кеш разрешённых id (для отладки)

После первого успешного разрешения handle/URL бот автоматически заменит запись на стабильный UC id и сохранит его в `yt_channels.json`, чтобы в будущем не делать HTML-lookup.

### Шаг 4: Мониторинг

Бот автоматически проверяет:
- **YouTube каналы** из `YT_CHANNELS` (каждые 30 минут)
- **GitHub релизы** из `allowed_domains` (на основе списка разрешенных репозиториев)

### Шаг 5: Запуск бота

```bash
python main.py
```

Бот готов к работе! 🎉

---

## 📋 Команды

### Для всех пользователей

| Команда | Описание | Пример |
|---------|----------|--------|
| `/start` | Приветствие и основная информация | `/start` |
| `/help` | Список всех команд | `/help` |
| `/search <запрос>` | Поиск гайдов по ключевым словам | `/search atmosphere` |
| `/latest` | Показать последние добавленные гайды | `/latest` |
| `/categories` | Категории гайдов | `/categories` |

### Для администраторов

| Команда | Описание | Пример |
|---------|----------|--------|
| `/sync` | Принудительная синхронизация | `/sync` |
| `/stats` | Статистика бота | `/stats` |
| `/cache_clear` | Очистить кэш | `/cache_clear` |

---

## 🛠️ Технический стек

```yaml
Основной:
  - Python: 3.9+
  - python-telegram-bot: 20.x
  - aiohttp: для async HTTP-запросов
  
Парсинг:
  - feedparser: YouTube RSS
  - BeautifulSoup4: GitHub Releases
  
Поиск:
  - fuzzywuzzy: нечёткий поиск
  - python-Levenshtein: оптимизация поиска
  
Деплой:
  - Railway: хостинг и CI/CD
  - python-dotenv: управление env
```

---

## 🚀 Деплой на Railway

### Быстрый деплой

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/YOUR_TEMPLATE_ID)

### Ручной деплой

1. **Создайте аккаунт на [Railway](https://railway.app/)**

2. **Создайте новый проект**:
   ```bash
   railway init
   ```

3. **Добавьте environment variables** в Railway Dashboard:
   - `BOT_TOKEN`
   - `ADMIN_IDS`
   - `YT_CHANNELS`
   - `ALLOWED_DOMAINS`
   - `PORT` (по умолчанию: `8080`)

4. **Задеплойте**:
   ```bash
   railway up
   ```

### 🔧 Настройки Railway

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python main.py",
    "restartPolicyType": "ALWAYS"
  }
}
```

---

## 🔒 Безопасность

### Whitelist доменов

Бот работает только с доверенными источниками:

```python
ALLOWED_DOMAINS = [
    'youtube.com',
    'youtu.be',
    'github.com',
    'nh-server.github.io'
]
```

### Управление доступом

- **Admin-only команды** защищены декораторами
- **Rate limiting** для предотвращения спама
- **Input validation** для всех пользовательских запросов

### Логирование

```python
# Все действия логируются
logger.info(f"User {user_id} searched for: {query}")
logger.warning(f"Unauthorized access attempt from {user_id}")
```

---

## 🎯 Use Cases

### 1. Поиск гайдов по установке Atmosphere
```
/search atmosphere install
```
Бот найдёт все релевантные видео и статьи.

### 2. Отслеживание новых релизов
Бот автоматически уведомляет о:
- Новых видео на YouTube каналах
- Новых релизах на GitHub

### 3. База знаний для сообщества
Администраторы могут:
- Добавлять новые источники
- Модерировать контент
- Получать статистику использования

---

## 🗺️ Roadmap

### Ближайшие планы
- [ ] Многоязычная поддержка (EN, RU, JP)
- [ ] Интеграция с Discord
- [ ] Расширенная аналитика
- [ ] Система рекомендаций на основе ML

### Долгосрочные планы
- [ ] Веб-интерфейс для управления
- [ ] Система рейтинга гайдов
- [ ] Уведомления о новых гайдах
- [ ] API для сторонних приложений

---

## 🙏 Благодарности

### 🛠️ Технологии
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — основной фреймворк
- [fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy) — нечёткий поиск
- [Railway](https://railway.app/) — хостинг и деплой

### 🌟 Вдохновение
- Nintendo Switch Homebrew Community
- [NH Switch Guide](https://nh-server.github.io/switch-guide/)
- [Atmosphere](https://github.com/Atmosphere-NX/Atmosphere)

### 👨‍💻 Автор
Создано с ❤️ [@Dimasick-git](https://github.com/Dimasick-git)

---

## 📄 Лицензия

Этот проект распространяется под лицензией MIT. Подробности в файле [LICENSE](LICENSE).

---

## 📞 Контакты и поддержка

- 🐛 **Нашли баг?** [Создайте Issue](https://github.com/Dimasick-git/Ryazhenka_Bot/issues)
- 💬 **Есть вопросы?** [Обсуждения](https://github.com/Dimasick-git/Ryazhenka_Bot/discussions)
- ⭐ **Нравится проект?** Поставьте звезду на GitHub!

---

<div align="center">

### 🎮 Happy Modding! 🎮

*Сделано для сообщества Nintendo Switch энтузиастов*

[![Star History](https://img.shields.io/github/stars/Dimasick-git/Ryazhenka_Bot?style=social)](https://github.com/Dimasick-git/Ryazhenka_Bot/stargazers)

</div>
