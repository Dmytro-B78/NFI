# ================================================================
# Freqtrade Futures Bot -- SYSTEM KNOWLEDGE BASE
# Strategy: NostalgiaForInfinityX7
# Audit date: 2026-06-20 (rev. 4)
# Status: DRY-RUN на сервере (systemd), первый бэктест запущен локально
# ================================================================

## OVERRIDES TO PROJECT_INSTRUCTIONS.md (universal)

Этот проект отличается от других в нескольких пунктах -- здесь они приоритетнее
universal-файла (SYSTEM_KNOWLEDGE.md > PROJECT_INSTRUCTIONS.md):

- **Уровень коммуникации: новичок** -- каждый шаг объяснять подробно, не считать
  Freqtrade/биржевые термины очевидными
- **"Тесты" != pytest.** В этом проекте тесты -- это `freqtrade backtesting` /
  `hyperopt` на исторических данных. Юнит-тестов кода нет и не планируется --
  это чужая стратегия, не наш код.
- **Не редактировать .py стратегии без явного решения.** Поведение бота меняем
  через config.json (пары, leverage, stake, max_open_trades, protections), а не
  правкой логики стратегии. Любая правка .py -- отдельное обсуждение, не дефолт.
- **Малые выборки -- explicit caution.** Dry-run/backtest результаты до
  ~30-50 сделок не считаются подтверждённой эффективностью, это всегда
  проговаривается, а не замалчивается.
- **Команды вместо ручного редактирования.** Пользователь предпочитает готовые
  команды (PowerShell `Set-Content`/here-string или точечный `-replace`/JSON-правка
  локально, `sudo tee` с heredoc на сервере), а не инструкции "открой в
  Notepad/nano и вставь".

---

## PROJECT STATE

| Parameter      | Value                                                          |
|----------------|------------------------------------------------------------------|
| Local root     | C:\TradingBots\NFI\                                              |
| Server         | 62.84.182.36, /home/ubuntu/NFI (Ubuntu), пользователь root        |
| GitHub repo    | https://github.com/Dmytro-B78/NFI (public, без секретов)         |
| Exchange       | Binance Futures (isolated margin)                                |
| Strategy       | NostalgiaForInfinityX7 v17.4.261 (community, repo iterativv/NostalgiaForInfinity) |
| Mode           | DRY-RUN на сервере (systemd) -> план Real money                  |
| Python         | 3.12.10 (venv локально: `venv\`; на сервере: `.venv/`)            |
| Freqtrade      | 2026.5.1 (переустановлен на сервере заново)                      |
| FreqUI         | http://localhost:8080 (freqtrade / freqtrade123)                 |
| Server port    | 8080 свободен, конфликтов с двумя другими ботами на сервере нет  |
| systemd unit   | /etc/systemd/system/freqtrade-nfi.service, enabled               |

Note: версия и дата последнего апдейта стратегии не проверены против upstream --
требует сверки при первом реальном разборе файла.

---

## DEPLOYMENT (обновлено 2026-06-20)

Бот перенесён с локальной Windows-машины на Ubuntu-сервер, рядом с двумя другими
(не связанными) ботами на той же машине. Запущен в режиме systemd-сервиса.

Сделано (хронологически):
1. Создан `.gitignore` (исключены `.env`, `config-private.json`, `data/`, `logs/`,
   `.venv/`, `.idea/`)
2. Из staging убраны `.idea/` (IDE-мусор) и `main.py` (пустой PyCharm-шаблон, не
   от пользователя)
3. `config-private.json` НЕ закоммичен (пустые плейсхолдеры под exchange API ключи
   на будущее) -- вместо него в репо `config-private.json.example`
4. Репозиторий создан и запушен (10 файлов, без секретов)
5. На сервере: `git clone`, `.venv`, freqtrade 2026.5.1 установлен
6. Секреты (`.env`, `config-private.json`) перенесены на сервер вручную через
   `scp` (НЕ через git)
7. **Локальный** `user_data\config.json`: `add_config_files` исправлены с
   абсолютных Windows-путей (`C:/TradingBots/NFI/user_data/...`) на относительные
   **имена файлов без префикса `user_data/`** -- freqtrade резолвит эти пути
   относительно папки самого `config.json` (т.е. `user_data\`), поэтому префикс
   дублировал путь и ломал загрузку. Подтверждено через `show-config` (чисто).
   Закоммичено и запушено (`699c8e1`).
8. Первый запуск бота на сервере в foreground -- подтверждён чистый старт:
   стратегия загрузилась, pairlist собран, heartbeat стабилен
9. Создан systemd-юнит `/etc/systemd/system/freqtrade-nfi.service`. По пути
   потребовалось два фикса:
   - `User=ubuntu` -> `User=root` (на сервере нет отдельного юзера `ubuntu`,
     реально используется `root`)
   - `ExecStart` путь к python поправлен с `venv/bin/python` на
     `.venv/bin/python` (реальное имя venv-папки на сервере -- `.venv`)
   - добавлена строка `EnvironmentFile=/home/ubuntu/NFI/.env` -- без неё
     systemd запускал процесс в чистом окружении без переменных
     `FREQTRADE__API_SERVER__JWT_SECRET_KEY` и др., и валидация конфига падала
     (`jwt_secret_key` пустой, `minLength: 32`)
10. После фиксов: `systemctl status` -> `active (running)`, в `journalctl`
    подтверждён чистый старт (state RUNNING, dry-run, pairlist 80 пар,
    без ошибок)
11. На сервере обнаружено: `user_data/config.json` имел незакоммиченную локальную
    правку (тот же фикс путей, что и в п.7, сделан вручную на сервере раньше).
    При следующем `git pull` это вызвало конфликт -- решено через `git restore`
    (локальная правка дублировала входящий коммит, отбрасывать безопасно).

Текущий unit-файл (`/etc/systemd/system/freqtrade-nfi.service`):

    [Unit]
    Description=Freqtrade NFI X7 bot
    After=network.target

    [Service]
    Type=simple
    User=root
    WorkingDirectory=/home/ubuntu/NFI
    EnvironmentFile=/home/ubuntu/NFI/.env
    ExecStart=/home/ubuntu/NFI/.venv/bin/python -m freqtrade trade --config user_data/config.json --strategy NostalgiaForInfinityX7
    Restart=on-failure
    RestartSec=10

    [Install]
    WantedBy=multi-user.target

Риск рассинхронизации путей между локальным и серверным config.json --
**закрыт повторно**: оба синхронизированы через git (см. п.11), workflow
"local-first -> push -> pull на сервере" подтверждён рабочим на практике.

---

## CONFIRMED BASELINE

### Прежняя локальная установка (для истории, не относится к текущему серверу)

| Метрика  | Значение         |
|----------|------------------|
| Trades   | 15               |
| WR       | 93%              |
| Profit   | +92.629 USDT     |
| Balance  | 683.129 USDT (dry) |
| Start    | 13.06.2026 22:00 |
| Uptime   | ~137 часов        |

### Серверная установка (текущая, под systemd)

| Метрика  | Значение         |
|----------|------------------|
| Trades   | 0 (только запущен) |
| Start    | 20.06.2026 23:41 CEST (рестарт после смены dry_run_wallet) |
| dry_run_wallet | 1000 USDT (было 10000, изменено по запросу пользователя -- "ещё нет 10К") |

ВАЖНО: 15 сделок прежней установки -- статистически незначимая выборка в любом
случае; WR=93% не является подтверждённой эффективностью стратегии с 18 режимами
входа. Серверный baseline пустой (обнулён рестартом), требует накопления данных
заново.

---

## STRATEGY FACTS (общие сведения о NFI X7, не специфика данной установки)

- Седьмая итерация community-стратегии NostalgiaForInfinity (разработчик iterativv)
- Установленная версия: v17.4.261 (подтверждено из лога запуска на сервере)
- Базовый таймфрейм 5m, индикаторы с нескольких старших таймфреймов,
  требует 800 свечей истории для валидных сигналов (startup_candle_count)
- Информативные таймфреймы (informative_pairs) для бэктеста используются
  предположительно 15m/1h/4h/1d по опыту сообщества NFI -- **не сверено** с
  фактическим кодом `NostalgiaForInfinityX7.py` в этом репо. Если бэктесту не
  хватит каких-то TF, freqtrade явно укажет, для какой пары/таймфрейма нет данных
- 18 торговых режимов: 10 long + 8 short, разные entry tags, риск-профили,
  размеры позиций и стратегии выхода
- Трёхуровневая система стоп-лосса (разные пороги для spot и futures)
- Две grinding-системы: Grinding v1 (6 уровней) и Grinding v2 (derisk + buyback) --
  механизмы усреднения позиции, основной источник риска при изолированной марже.
  `grinding_enable: true` подтверждено в `show-config`
- X7 -- наиболее активно разрабатываемая ветка; X6 считается более стабильной
  для продакшена (по состоянию на внешние источники, не подтверждено для
  установленной версии)
- В репозитории есть nfi-updater -- сервис автообновления стратегии/blacklist/pairlist;
  не подтверждено, используется ли он в данной установке
- **Leverage и protections не настроены через config.json** -- подтверждено через
  `show-config` (оба ключа отсутствуют в объединённом конфиге). Если используются --
  то зашиты в `.py` стратегии. `protectionmanager` в логе сервера подтвердил:
  "No protection Handlers defined"
- max_open_trades: 6, stake_amount: unlimited, stoploss: -0.99,
  position_adjustment_enable: True, tradable_balance_ratio: 0.99 (из `show-config`)

---

## KEY FILES

    Локально: C:\TradingBots\NFI\
    Сервер:   /home/ubuntu/NFI\

      user_data\
        config.json                основной конфиг -- пары, leverage (не настроено),
                                    stake, protections (не настроено)
                                    (add_config_files -- относительные имена файлов,
                                    без префикса user_data/)
        exampleconfig.json         содержит `dry_run_wallet` (1000 USDT, см. Baseline) --
                                    НЕ строгий JSON (есть `//`-комментарии), freqtrade
                                    парсит нормально, но PowerShell ConvertFrom-Json
                                    падает -- править только через текстовый -replace,
                                    не через JSON-парсинг
        config-private.json        секреты (НЕ в git, перенесён вручную через scp)
        pairlist-static-backtest.json  НОВЫЙ, локальный, НЕ в git (рабочий файл для
                                    бэктеста) -- оверлей StaticPairList с фиксированным
                                    снимком 80 пар (снято 20.06.2026 через
                                    `test-pairlist`), т.к. динамические пейрлисты
                                    (VolumePairList/AgeFilter/SpreadFilter/
                                    RangeStabilityFilter) бэктестинг не поддерживает
        strategies\
          NostalgiaForInfinityX7.py  стратегия -- НЕ редактировать без решения
        logs\
          freqtrade.log
      .env                          переменные окружения (JWT secret, API user/pass) --
                                     НЕ в git, на сервере подключается через
                                     EnvironmentFile в systemd-юните

    GitHub: https://github.com/Dmytro-B78/NFI

    Сервер, systemd: /etc/systemd/system/freqtrade-nfi.service

---

## LAUNCH COMMAND (локально, Windows)

    cd C:\TradingBots\NFI
    venv\Scripts\activate
    chcp 65001; $env:PYTHONIOENCODING="utf-8"; python -m freqtrade trade --config user_data/config.json --strategy NostalgiaForInfinityX7

## LAUNCH (сервер, Ubuntu) -- через systemd (текущий рабочий способ)

    sudo systemctl start freqtrade-nfi      # запуск
    sudo systemctl stop freqtrade-nfi       # остановка
    sudo systemctl restart freqtrade-nfi    # перезапуск (после правки config.json и т.п.)
    sudo systemctl status freqtrade-nfi     # текущий статус
    journalctl -u freqtrade-nfi -n 50 --no-pager   # последние 50 строк лога
    journalctl -u freqtrade-nfi -f                 # live-логи

Альтернатива (foreground, для разовой ручной отладки, не для постоянной работы):

    cd /home/ubuntu/NFI
    source .venv/bin/activate
    python -m freqtrade trade --config user_data/config.json --strategy NostalgiaForInfinityX7

---

## BACKTESTING (локально, Windows) -- ПЕРВЫЙ ЗАПУСК В ПРОЦЕССЕ (20.06.2026)

### Обязательный шаг перед любой командой (download-data / backtesting / test-pairlist)

`config-private.json` локально содержит пустой `jwt_secret_key`. Freqtrade
валидирует весь конфиг целиком (включая `api_server`) даже для команд, которые
API-сервер не используют -- иначе падает с `'' is too short`. Решение: задать
переменную окружения на сессию PowerShell (тот же паттерн, что и в
`EnvironmentFile` на сервере), без правки секретных файлов:

    $env:FREQTRADE__API_SERVER__JWT_SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})

Переменная живёт только в текущем окне PowerShell -- задавать один раз на сессию.

### Динамический пейрлист не поддерживается бэктестом

`config.json` использует `VolumePairList` + фильтры (`AgeFilter`, `SpreadFilter`,
`RangeStabilityFilter`) -- они требуют live-данные биржи и не работают в
бэктесте/`download-data`. Решение: статический оверлей
`user_data/pairlist-static-backtest.json` (см. KEY FILES) со снимком пар,
полученным через `freqtrade test-pairlist`. Подключается как второй `--config`
поверх основного.

### Рабочие команды

    cd C:\TradingBots\NFI

    # 1. скачать историю (один раз на нужный период/таймфреймы)
    freqtrade download-data `
      --config user_data/config.json `
      --config user_data/pairlist-static-backtest.json `
      --timeframes 5m 15m 1h 4h 1d `
      --timerange 20250101-20260620

    # 2. бэктест
    freqtrade backtesting `
      --config user_data/config.json `
      --config user_data/pairlist-static-backtest.json `
      --strategy NostalgiaForInfinityX7 `
      --timerange 20250101-20260620 `
      --timeframe 5m `
      --export trades `
      --export-filename backtest_results_nfi_x7 `
      --breakdown day week month `
      --cache none

ВАЖНО (survivorship bias): статический список пар -- это снимок топ-80 по объёму
на 20.06.2026. Для более ранних периодов (начало 2025) реальный состав топ-пар по
объёму мог отличаться -- это вносит смещение в результат бэктеста, держать в уме
при интерпретации цифр.

Результат первого прогона -- пока не получен (история ещё качается на момент
последнего аудита).

---

## LOG WORKFLOW

Локально:

    Get-Content "C:\TradingBots\NFI\user_data\logs\freqtrade.log" | Select-Object -Last 50

На сервере -- через systemd journal (не напрямую файл лога):

    journalctl -u freqtrade-nfi -n 50 --no-pager

При диагностике конкретной проблемы -- grep по паре или ключевому слову ошибки.

---

## KNOWN ISSUES (не переоткрывать)

- UnicodeEncodeError в консоли (локально, Windows) -- стратегия генерирует emoji
  в strategy_msg. Не влияет на торговлю. Игнорировать.
- На сервере venv-папка называется `.venv` (скрытая), а не `venv` -- учитывать
  в любых путях/командах, связанных с сервером.
- На сервере нет пользователя `ubuntu` -- реально используется `root`
  (несмотря на то, что путь к проекту `/home/ubuntu/NFI`).
- Systemd запускает процессы в чистом окружении -- любые переменные из `.env`
  должны быть явно подключены через `EnvironmentFile=` в unit-файле, иначе
  валидация конфига падает на `jwt_secret_key` (и потенциально на других
  env-зависимых полях).
- **Локально, при любой freqtrade-команде** (не только `trade`): та же проблема
  с пустым `jwt_secret_key` в `config-private.json` -- лечится через
  `$env:FREQTRADE__API_SERVER__JWT_SECRET_KEY` на сессию PowerShell (см.
  BACKTESTING). Не путать с серверным фиксом -- это разные окружения, переменная
  не персистентна между сессиями PowerShell.
- **Бэктест/download-data не работают с динамическим пейрлистом** (VolumePairList
  и зависимые фильтры) -- нужен статический оверлей с фиксированным списком пар
  (см. `pairlist-static-backtest.json` в KEY FILES).
- **`exampleconfig.json` содержит `//`-комментарии** -- невалидный строгий JSON,
  freqtrade парсит нормально, но `ConvertFrom-Json` в PowerShell падает. Править
  только текстовым `-replace`, не JSON-парсингом.
- **`git pull` на сервере может конфликтовать** с локальными незакоммиченными
  правками `config.json` (см. DEPLOYMENT п.11) -- перед pull всегда проверять
  `git status`/`git diff`, не затирать вслепую.

---

## ROADMAP

| Шаг | Статус |
|-----|--------|
| STEP 1: Установка и настройка | DONE (13.06.2026) |
| STEP 2: Наблюдение dry_run 1-2 недели | IN PROGRESS (на сервере, под systemd, перезапущен 20.06.2026 23:41, баланс 1000 USDT) |
| STEP 3: Бэктест на исторических данных | IN PROGRESS (локально, первый прогон, история качается) |
| STEP 4: Оптимизация (Hyperopt) | NOT STARTED |
| STEP 5: Реальная торговля (API ключи + dry_run=false) | NOT STARTED |
| STEP 6: Масштабирование + Telegram + VPS | DONE -- сервер настроен, бот запущен в trade-режиме под systemd |
| STEP 7: FreqAI | дальняя цель |

---

## NEXT STEP

Дождаться результатов первого бэктеста (20250101-20260620, 80 пар, статический
снимок). Параллельно наблюдать dry-run на сервере (баланс 1000 USDT, накопление
с нуля после рестарта 20.06.2026 23:41).

---

## PENDING

- Результат первого бэктеста -- ещё не получен (история докачивается)
- Информативные таймфреймы NFI X7 (15m/1h/4h/1d) -- предположение по опыту
  сообщества, не сверено с фактическим кодом `.py`
- leverage-логика стратегии не проверена -- искать в .py файле (не в config.json,
  это подтверждено)
- exchange.key/secret для боевого режима -- шаг 5 роадмапа, пока не трогаем
- Сверить версию стратегии (дата последнего коммита) против актуальной на GitHub
  (iterativv/NostalgiaForInfinity)
- Telegram-уведомления выключены (`telegram.enabled: false`) -- решить, включать ли
- `tradesv3.dryrun.sqlite*` на сервере -- untracked в git, не блокирует работу,
  но стоит когда-нибудь добавить в `.gitignore` (не сделано, не дефолтное действие)
- survivorship bias в текущем бэктесте (статический снимок пар на 20.06.2026,
  применяется ко всему периоду 2025-2026) -- учитывать при интерпретации результата

---

## AUDIT LOG

| Date       | Status | Notes                                                    |
|------------|--------|------------------------------------------------------------|
| 2026-06-20 | INIT   | Проект выделен из общего чата. Baseline зафиксирован со слов пользователя (15 trades, WR 93%, +92.629 USDT), файлы стратегии и config.json ещё не получены. |
| 2026-06-20 | UPDATE | Деплой на Ubuntu-сервер: GitHub-репо создан и запушен, freqtrade переустановлен на сервере, секреты перенесены через scp, пути в config.json переведены на относительные. Бот ещё не запущен в trade-режиме. Локальный config.json на Windows ещё не поправлен (риск конфликта при следующем push). |
| 2026-06-20 | UPDATE | Локальный config.json поправлен (add_config_files -- имена файлов без префикса user_data/), проверен через show-config, закоммичен и запушен (699c8e1). Бот успешно запущен на сервере в foreground (чистый старт, без ошибок). Оформлен как systemd-сервис freqtrade-nfi (после фиксов User=root, .venv путь, EnvironmentFile=.env) -- статус active (running), подтверждён чистый старт через journalctl. STEP 6 роадмапа закрыт. |
| 2026-06-20 | UPDATE | Начата подготовка к бэктесту (STEP 3): обнаружен и решён конфликт jwt_secret_key для локальных команд (env var), обнаружено и решено несовместимость динамического пейрлиста с бэктестом (статический оверлей pairlist-static-backtest.json, снимок 80 пар через test-pairlist). Через show-config сверены реальные параметры конфига (баланс, leverage/protections не в config.json, telegram выключен). По запросу пользователя dry_run_wallet изменён с 10000 на 1000 USDT -- локально (exampleconfig.json, текстовой правкой из-за // комментариев) и на сервере (через git push/pull, с разрешением конфликта git restore -- локальная правка на сервере дублировала уже запушенный фикс путей). Бот на сервере перезапущен с новым балансом, чистый старт подтверждён. Первый прогон бэктеста запущен, история докачивается, результат ещё не получен. |

---
*End of SYSTEM_KNOWLEDGE.md*