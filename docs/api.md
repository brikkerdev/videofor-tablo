# HTTP API сервиса интеграции

Справочник всех эндпоинтов. Базовый адрес: `http://<host>:<APP_PORT>` (по умолчанию `:8000`). Тела запросов и ответов — JSON.

## Аутентификация

Токен `X-API-Key` проверяется **только** на `POST /api/events` и только если в конфигурации задан `API_KEY`. Все остальные эндпоинты (управление через веб-интерфейс) аутентификации не требуют и рассчитаны на доверенную сеть. Если вынесете API наружу — закройте его на уровне сети или обратного прокси.

## Формат ошибок

Ошибки валидации тела и `HTTPException` возвращаются единым конвертом:

```json
{ "status": "error", "message": "<текст>" }
```

| Код | Когда |
| --- | --- |
| 400 | Невалидное тело запроса (`Invalid request body`) или нет правила под событие (`Invalid event type`) |
| 401 | Неверный/отсутствующий `X-API-Key` на `/api/events` (`Unauthorized`) |
| 404 | Показатель не найден |
| 409 | Показатель с таким ключом уже существует |
| 502 | Не удалось погасить табло (`/api/display/clear`) |

---

## События

### POST /api/events

Приём события от «Видеофора».

**Заголовки:** `X-API-Key: <token>` (если задан `API_KEY`).

**Тело:**

| Поле | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `event_type` | string | да | Тип события |
| `event_time` | datetime ISO 8601 | да | Время события. Без таймзоны — трактуется в поясе сервиса |
| `source` | string | да | Источник, ожидается `Videofor` |
| `object_type` | string | нет | Тип объекта (`transport`, `student`, `instructor`) |
| `checkpoint` | string | нет | Точка фиксации, напр. `TK1` |
| `value` | integer | да | Значение / признак изменения |

```json
{
  "event_type": "violation",
  "event_time": "2026-06-16T10:15:00",
  "source": "Videofor",
  "object_type": "transport",
  "checkpoint": "TK1",
  "value": 1
}
```

**Ответ 200:**

```json
{
  "status": "success",
  "message": "Data received and displayed",
  "received_at": "2026-06-16T10:15:05+03:00"
}
```

**Поведение:**
- Тип события всегда регистрируется в `observed_events` (даже если правила нет).
- Если ни одно правило в `event_rules` не подходит → `400 Invalid event type`, в `events` не пишется.
- Подходящие правила применяются (`inc`/`dec`/`set`); событие и новые значения счётчиков пишутся одной транзакцией.
- Недоступность табло на приём не влияет — доставка идёт фоном.

---

## Состояние показателей

### GET /api/state

Текущее состояние (из кэша в памяти). Служебный эндпоинт для отладки — табло работает по push-модели.

```json
{
  "date": "2026-06-16",
  "updated_at": "2026-06-16T10:15:05+03:00",
  "indicators": [
    {"key": "violations_day", "display_name": "Нарушения за день", "value": 12},
    {"key": "students_on_track", "display_name": "Ученики на треке", "value": 16},
    {"key": "instructors_on_track", "display_name": "Инструкторы на треке", "value": 3}
  ]
}
```

Список — включённые показатели в порядке `sort_order`.

### POST /api/state/adjust

Ручная коррекция значения показателя (например, исправить ошибку счёта).

**Тело:** `{ "key": "students_on_track", "delta": -1 }`

`delta` может быть отрицательной; результат не опускается ниже нуля. Значение пишется в `counter_values` за текущий день, состояние помечается dirty.

**Ответ:** `{ "key": "students_on_track", "value": 15 }`

---

## Вывод на табло

### GET /api/display/config

Текущая конфигурация вывода, список показателей и параметры панели.

```json
{
  "board": { /* BoardConfig, см. ниже */ },
  "indicators": [
    {"key": "violations_day", "display_name": "Нарушения за день"}
  ],
  "device": { "width": 256, "height": 96 }
}
```

`device` — реальные размеры панели, прочитанные у шлюза по SSE (или дефолт 256×96).

### PUT /api/display/config

Сохранить конфигурацию вывода. Тело — объект `BoardConfig` целиком. Применяется немедленно и пушится на табло.

**Ответ:** `{ "board": { ... } }`

#### Объект BoardConfig

| Поле | Тип | По умолч. | Описание |
| --- | --- | --- | --- |
| `top_panel` | TopPanel | — | Верхняя плашка (часы, онлайн, текст) |
| `lines` | LineConfig[] | `[]` | Настройки строк показателей; порядок задаёт порядок вывода |
| `columns` | int | `1` | Колонок на экране (рендер ограничивает 1–2) |
| `padding` | int | `3` | Отступ текста от краёв, px (`0..40`) |
| `fontname` | string | `Arial` | Шрифт строк (из списка шрифтов шлюза) |
| `fontsize` | int | `16` | Базовый кегль; авто-уменьшается, чтобы текст влез |
| `stunt` | int | `0` | Эффект/анимация (`0` — статично) |
| `online_window_seconds` | int | `120` | Окно «онлайна»: если последнее событие новее — онлайн |
| `screen_brightness` | int | `255` | Базовая яркость экрана `0..255` |

**TopPanel:** `enabled`, `show_clock`, `show_online`, `text`, `datetime_format` (`%d.%m %H:%M`), `online_text` (`ON`), `offline_text` (`OFF`), `align` (`left`/`center`/`right`), `color` (`0xAARRGGBB`), `fontname`, `fontsize`, `height` (px), `stunt`, `brightness`.

**LineConfig:** `key` (ключ показателя), `enabled`, `color`, `brightness`, `smooth` (градиентная окраска по порогу), `threshold`.

**Threshold:** `value`, `op` (`>=`/`>`/`<=`/`<`/`==`), `color`, `target` (`line` — красить всю строку, иначе только значение). При `smooth: true` значение плавно меняет цвет по мере приближения к порогу.

### GET /api/display/preview

Области, которые уйдут на табло при текущем состоянии и конфигурации — для предпросмотра в UI. На устройство ничего не отправляет.

```json
{ "areas": [ { "id": "0", "msg": "...", "x": "0", "y": "0", "w": "...", "h": "...", "fontname": "Arial", "fontsize": "16", "fontcolor": "0xffffffff", "stunt": "0", "align": "left" } ] }
```

### POST /api/display/push

Принудительно перерисовать табло (помечает состояние dirty). Тело не нужно.

**Ответ:** `{ "status": "ok" }`

### POST /api/display/clear

Погасить табло и поставить пушер на паузу (чтобы экран не перерисовался автоматически). Возобновляется любым изменением состояния или `POST /api/display/push`.

**Ответ:** `{ "status": "ok" }`. При недоступном табло — `502`.

---

## Управление табло (шлюз)

### GET /api/tablo/status

Статус подключения к шлюзу и параметры панели.

```json
{
  "reachable": true,
  "connected": true,
  "url": "http://192.168.0.64",
  "device": { "width": 256, "height": 96, "brightness": 255 },
  "last_push": { "at": "10:15:05", "ok": true, "error": "" }
}
```

`reachable` — задан `TABLO_URL`; `connected` — шлюз подтвердил связь с матрицей по SSE; `last_push` — результат последней попытки доставки (`null`, если ещё не было).

### POST /api/tablo/reconnect

Переподключить шлюз (перезапуск SSE-потока). Запускается в фоне.

**Ответ:** `{ "status": "ok" }`

### POST /api/tablo/brightness

Яркость экрана.

**Тело:** `{ "value": 200 }` (`0..255`)

Применяется на шлюзе и сохраняется в `BoardConfig.screen_brightness`.

**Ответ:** `{ "status": "ok", "value": 200 }` (или `"unreachable"`, если шлюз не ответил).

---

## Конструктор показателей

Управление справочниками в рантайме. Любая мутация перечитывает кэш без рестарта (`reload_dictionaries`) и пушит на табло.

### GET /api/event-catalog

Агрегат для конструктора: типы событий с метаданными и привязками + список всех показателей.

```json
{
  "events": [
    {
      "event_type": "violation",
      "object_type": "transport",
      "checkpoint": null,
      "count": 42,
      "last_seen": "2026-06-16T10:15:00+03:00",
      "observed": true,
      "received": true,
      "status": "displayed",
      "mappings": [
        {
          "indicator_key": "violations_day",
          "display_name": "Нарушения за день",
          "op": "inc",
          "checkpoint": null,
          "rule_enabled": true,
          "indicator_enabled": true,
          "line_enabled": true
        }
      ]
    }
  ],
  "indicators": [
    {"key": "violations_day", "display_name": "Нарушения за день",
     "kind": "daily", "sort_order": 10, "enabled": true, "line_enabled": true}
  ]
}
```

`status` события:
- `unhandled` — приходило, но не привязано ни к одному показателю («необработанный запрос»);
- `configured` — привязано, но не выводится (показатель/правило/строка отключены);
- `displayed` — привязано и выводится на табло.

### POST /api/indicators

Создать показатель, опционально сразу с правилом.

**Тело:**

| Поле | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `key` | string | нет | Машинный ключ. По умолчанию — slug из `rule.event_type` или `display_name` |
| `display_name` | string | да | Подпись на табло |
| `kind` | `daily`\|`gauge` | нет | По умолчанию `daily` |
| `sort_order` | int | нет | По умолчанию `max(sort_order) + 10` |
| `rule` | RuleIn | нет | Если задано — сразу привязывает событие: `{event_type, checkpoint?, op}` |

```json
{
  "display_name": "Транспорт за день",
  "kind": "daily",
  "rule": { "event_type": "transport", "checkpoint": "TK1", "op": "inc" }
}
```

**Ответ:** `{ "status": "ok", "key": "transport_day" }`. Существующий ключ → `409`.

### PATCH /api/indicators/{key}

Изменить показатель. Передаются только меняемые поля: `display_name`, `kind`, `sort_order`, `enabled`. В UI вызывается кнопкой **«изменить»** в карточке показателя.

**Тело (все поля необязательны):**

```json
{ "display_name": "Нарушения за сутки", "kind": "daily", "sort_order": 10, "enabled": true }
```

**Ответ:** `{ "status": "ok" }`. Нет показателя → `404`.

### DELETE /api/indicators/{key}

Удалить показатель вместе с его правилами (`event_rules`) и историей значений (`counter_values`); строка убирается из конфигурации вывода.

**Ответ:** `{ "status": "ok" }`. Нет показателя → `404`.

### POST /api/event-rules

Привязать тип события к существующему показателю.

**Тело:** `{ "event_type": "transport", "checkpoint": "TK1", "indicator_key": "transport_day", "op": "inc" }`

`checkpoint` опционален (`null` — любая точка). Повторная привязка той же пары `(event_type, indicator_key)` обновляет `checkpoint`/`op` и включает правило.

**Ответ:** `{ "status": "ok" }`. Нет показателя → `404`.

### DELETE /api/event-rules

Отвязать правило. Параметры строки запроса: `event_type`, `indicator_key`.

```
DELETE /api/event-rules?event_type=transport&indicator_key=transport_day
```

**Ответ:** `{ "status": "ok" }`

### DELETE /api/event-catalog/{event_type}

Убрать тип события из реестра `observed_events` (например, мусорный тип, который больше не нужен в списке необработанных). На подсчёт показателей не влияет.

**Ответ:** `{ "status": "ok" }`

---

## Служебные

### GET /health

Живость сервиса и соединения с БД. Используется healthcheck'ом в compose.

**Ответ:** `{ "status": "ok" }`

### GET /

Редирект на `/ui/` (веб-интерфейс).

### /ui/

Веб-интерфейс «Конструктор показателей» (SPA, `app/static/index.html`).
