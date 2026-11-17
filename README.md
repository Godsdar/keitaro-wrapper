# Keitaro wrapper

Обёртка над [Keitaro Admin API](https://admin-api.docs.keitaro.io/) из двух частей:

1. **Создаватор кампаний** — по названию, гео и ID оффера создаёт кампанию
   с доменом, группой и источником и двумя потоками:
   - поток 1 ловит всех из указанных стран и редиректит на Google;
   - поток 2 отправляет всех остальных на выбранный оффер.
2. **Редактор кампании** — добавляет и удаляет офферы в потоках, пересчитывает
   доли, публикует изменения в Keitaro или откатывает их.

Стек: FastAPI, SQLAlchemy 2, Alembic, httpx; фронт — HTML + JavaScript без сборки.

## Быстрый старт

Нужен Python 3.11+ и [uv](https://docs.astral.sh/uv/) (или обычный pip, см. ниже).

```bash
git clone https://github.com/Godsdar/keitaro-wrapper.git
cd keitaro-wrapper
cp .env.example .env          # впишите KEITARO_API_KEY и свой CAMPAIGN_PREFIX
uv sync                       # зависимости в .venv
uv run alembic upgrade head   # миграции: создаёт таблицы в базе
uv run uvicorn app.main:app --port 8000
```

Откройте http://localhost:8000.

API-ключ: Keitaro → Профиль (правый верхний угол) → «API ключи».

Без uv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --port 8000
```

## Миграции

Схема базы ведётся через Alembic (`migrations/`).

| Действие | Команда |
|---|---|
| Применить все миграции | `uv run alembic upgrade head` |
| Откатить последнюю | `uv run alembic downgrade -1` |
| Текущая версия базы | `uv run alembic current` |
| Новая миграция после правки `app/models.py` | `uv run alembic revision --autogenerate -m "описание"` |

Адрес базы берётся из `DATABASE_URL` в `.env` (по умолчанию SQLite-файл
`keitaro_wrapper.db`). Для PostgreSQL установите драйвер
(`uv add "psycopg[binary]"`) и укажите
`DATABASE_URL=postgresql+psycopg://user:pass@localhost/keitaro`.

## Настройки (.env)

| Переменная | Что это | По умолчанию |
|---|---|---|
| `KEITARO_URL` | адрес трекера без `/admin` | `https://tlgk.host` |
| `KEITARO_API_KEY` | ключ Admin API | — |
| `CAMPAIGN_PREFIX` | префикс имени, добавляется ко всем новым кампаниям | `test_familiya_` |
| `DEFAULT_DOMAIN`, `DEFAULT_GROUP`, `DEFAULT_SOURCE` | что выбрано в форме по умолчанию (по имени) | `in.posdk.xyz`, `FORTESTS`, `FORTESTS` |
| `GEO_REDIRECT_URL` | куда редиректит гео-поток | `https://www.google.com` |
| `DATABASE_URL` | база обёртки | `sqlite:///./keitaro_wrapper.db` |

## Как это работает

### Создаватор

Форма: название, гео (`AU` или `MX,AU,RO`), оффер — поиск с автокомплитом
по названию или ID (идёт в Keitaro через наш API). Домен, группа и источник
подставлены по умолчанию, их можно поменять в «Domain, group, source».

Что отправляется в Keitaro:

1. `POST /campaigns` — имя с префиксом, случайный alias, `domain_id`,
   `group_id`, `traffic_source_id`, ротация потоков по позиции.
2. `POST /streams` — «Geo AU → Google»: позиция 1, схема `redirect`,
   фильтр `country` в режиме `accept` с выбранными странами.
3. `POST /streams` — «Offers»: позиция 2, схема `landings`, оффер с долей 100%.

Если поток создать не удалось, полусозданная кампания уходит в архив
Keitaro, чтобы не оставлять «пустых» кампаний.

### Редактор

Логика повторяет существующую обёртку из видео.

- **Fetch streams from KT** — забирает потоки кампании. Потоки с офферами
  показываются таблицей офферов и долей; потоки без офферов (например,
  гео-редирект) — просто как поток, без разбора содержимого.
- **Add** — добавляет оффер (поиск с автокомплитом); доли пересчитываются.
  Поток становится жёлтым: изменения есть только в обёртке, в Keitaro их нет.
- **Push to KT** — отправляет активные офферы с долями в Keitaro
  (`PUT /streams/{id}`), ответ Keitaro становится новым опубликованным
  состоянием.
- **Cancel** — откатывает неопубликованные изменения: добавленные офферы
  удаляются из базы, удалённые возвращаются, доли — как в Keitaro.
- **Remove** — оффер сереет, его доля 0%. После Push он исчезает из Keitaro,
  но остаётся у нас в архиве с кнопкой **Bring back**.
- Если оффер удалили прямо в Keitaro, при следующем Fetch он у нас не
  пропадает, а переходит в статус removed (серый) с кнопкой Bring back.
- **📌 Pin** — закрепляет долю оффера. Любое поле доли можно поправить
  руками — такая доля закрепляется автоматически.

### Как считаются доли

В Keitaro доля оффера — целое число процентов, сумма по потоку — ровно 100.

- закреплённые доли не меняются;
- остаток `100 − сумма закреплённых` делится поровну между незакреплёнными
  активными офферами; если не делится нацело, лишний процент по одному
  получают первые офферы: 3 оффера → 34 / 33 / 33;
- у удалённых — 0%.

Пример: оффер A закреплён на 25%, ещё три оффера делят 75% → 25 / 25 / 25.
Удаляем один → 25 / 38 / 37. Если закреплённые в сумме больше 100%,
операция отклоняется; если сумма не 100% и делить остаток некому,
кнопка Push неактивна, а под потоком видна причина.

### Что лежит в базе

| Таблица | Что хранит |
|---|---|
| `campaigns` | кампании, которые открывали или создавали в обёртке; для созданных — гео, оффер, домен, группа, источник |
| `streams` | потоки кампаний (ID в Keitaro, имя, тип, схема, позиция) |
| `stream_offers` | привязки офферов к потокам: черновик (`status`, `share`, `pinned`) и опубликованное состояние (`pub_status`, `pub_share`) |

Разница между черновиком и опубликованным состоянием — это и есть «жёлтый»
поток; Cancel возвращает черновик к опубликованному, Push и Fetch обновляют
опубликованное по ответу Keitaro.

## API

Swagger: http://localhost:8000/docs

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/settings` | домены, группы, источники, значения по умолчанию |
| GET | `/api/offers?q=` | поиск офферов для автокомплита |
| POST | `/api/campaigns` | создать кампанию с двумя потоками |
| GET | `/api/campaigns?all=false` | кампании из Keitaro (по умолчанию только с префиксом) |
| GET | `/api/campaigns/{keitaro_id}` | открыть кампанию в редакторе |
| POST | `/api/campaigns/{keitaro_id}/fetch` | Fetch streams |
| POST | `/api/streams/{id}/offers` | добавить оффер |
| POST | `/api/streams/{id}/offers/{row}/remove` | удалить оффер |
| POST | `/api/streams/{id}/offers/{row}/bring-back` | вернуть оффер |
| PATCH | `/api/streams/{id}/offers/{row}` | `{"pinned": true}` или `{"share": 40}` |
| POST | `/api/streams/{id}/push` | опубликовать поток в Keitaro |
| POST | `/api/streams/{id}/cancel` | отменить неопубликованные изменения |

## Тесты

```bash
uv run pytest
```

Тесты не ходят в настоящий Keitaro: используется поддельный клиент в памяти
(`tests/conftest.py`). Покрыты пересчёт долей и сценарии из видео — добавление,
Push, Cancel, Remove → архив → Bring back, удаление оффера прямо в Keitaro,
закреплённые доли, создание кампании и откат при ошибке.

## Структура

```
app/
  main.py      FastAPI-приложение, статика, обработка ошибок Keitaro
  api.py       HTTP-эндпоинты
  creator.py   создание кампании и двух потоков
  editor.py    Fetch, черновик офферов, Push, Cancel
  weights.py   пересчёт долей
  keitaro.py   клиент Keitaro Admin API
  models.py    таблицы SQLAlchemy
  db.py, config.py
migrations/    Alembic
static/        index.html, app.js, style.css
tests/
```
