# ================================================================
# Freqtrade Futures Bot -- SYSTEM KNOWLEDGE BASE
# Strategy: NostalgiaForInfinityX7
# Audit date: 2026-06-25 (rev. 7)
# Status: DRY-RUN на сервере (systemd), финальный набор шорт-условий задеплоен
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
  Исключение: protections (см. ниже) и набор активных шорт-условий -- обе правки
  сделаны через явное обсуждение и подтверждение пользователем.
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
| Strategy       | NostalgiaForInfinityX7 v17.4.277 (community, repo iterativv/NostalgiaForInfinity) |
| Mode           | DRY-RUN на сервере (systemd) -> план Real money                  |
| Python         | 3.12.10 (venv локально: `venv\`; на сервере: `.venv/`) / локально freqtrade venv 3.13.1 (см. ниже) |
| Freqtrade      | 2026.5.1 (локально и на сервере)                                  |
| FreqUI         | http://localhost:8080 (freqtrade / freqtrade123)                 |
| Server port    | 8080 свободен, конфликтов с двумя другими ботами на сервере нет  |
| systemd unit   | /etc/systemd/system/freqtrade-nfi.service, enabled               |
| Реальный баланс пользователя | 1500 USDT (НЕ совпадает с dry_run_wallet/backtest-балансом 1000 USDT -- см. PENDING) |

---

## DEPLOYMENT (история, см. AUDIT LOG для деталей по датам)

Бот перенесён с локальной Windows-машины на Ubuntu-сервер, рядом с двумя другими
(не связанными) ботами на той же машине. Запущен в режиме systemd-сервиса.

Ключевые фиксы по пути (хронологически, кратко -- полное описание см. AUDIT LOG):
1. `.gitignore` создан, секреты (`.env`, `config-private.json`) исключены из git,
   перенесены на сервер вручную через `scp`
2. `add_config_files` в `config.json` исправлены с абсолютных Windows-путей на
   относительные имена файлов без префикса `user_data/` -- freqtrade резолвит
   эти пути относительно папки самого `config.json`
3. systemd-юнит `freqtrade-nfi.service` настроен и пофикшен:
   - `User=ubuntu` -> `User=root` (на сервере нет юзера `ubuntu`)
   - `venv/bin/python` -> `.venv/bin/python` (реальное имя venv-папки на сервере)
   - добавлена `EnvironmentFile=/home/ubuntu/NFI/.env` -- без неё systemd
     запускал процесс без `JWT_SECRET_KEY`, валидация конфига падала
4. Конфликт `git pull` на сервере (локальная незакоммиченная правка дублировала
   входящий коммит) -- решён через `git restore`

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

Workflow "local-first -> push -> pull на сервере" подтверждён рабочим на практике
(включая повторную проверку 25.06.2026 при обновлении стратегии до v17.4.277).

---

## CONFIRMED BASELINE

### Серверная установка (dry-run, под systemd)

| Метрика  | Значение         |
|----------|------------------|
| Start    | 21.06.2026 01:13 CEST (рестарт после смены dry_run_wallet на 1000) |
| dry_run_wallet | 1000 USDT |
| Код стратегии (шорт-условия) | обновлён 21.06.2026 14:26 CEST (финальный набор шорт-условий, commit 376627b) |
| Код стратегии (версия) | обновлён 25.06.2026 (v17.4.277 + блэклист IDOL/UB, commit 227d07d) -- баланс/счётчик сделок НЕ обнулялся, только код |

ВАЖНО: реальный баланс пользователя -- 1500 USDT, отличается от dry_run_wallet
(1000 USDT). Все бэктесты и текущий dry-run считаются на 1000 USDT. При переходе
к реальной торговле -- пересчитать stake_amount/max_open_trades под фактический
баланс (см. PENDING).

---

## STRATEGY FACTS (общие сведения о NFI X7)

- Седьмая итерация community-стратегии NostalgiaForInfinity (разработчик iterativv)
- Установленная версия: v17.4.277 (обновлено с v17.4.261, изменение: "fine tune the grind entries")
- Базовый таймфрейм 5m (подтверждено в логе сервера: `*Timeframe:* \`5m\``),
  startup_candle_count 800 свечей
- Информативные таймфреймы (15m/1h/4h/1d) -- предположение по опыту сообщества,
  **не сверено** с фактическим кодом `.py`. Базовый и информативные ТФ зашиты в
  `.py` (class attribute `timeframe` + `informative_pairs`), НЕ настраиваются
  через config.json. Изменение требует отдельного явного решения (правка .py) --
  не "попробовать другой ТФ" как лёгкий эксперимент, а фактически новый прогон с
  непредсказуемым результатом, т.к. вся логика входов тюнилась под 5m
- 18 торговых режимов: 10 long + 8 short, разные entry tags, риск-профили,
  размеры позиций и стратегии выхода
- Из ~11 потенциальных шорт-условий реализовано: 501-504, 541-543, 641, 642, 661.
  Условие 603 -- мёртвый флаг, блока логики для него нет
- **ФИНАЛИЗИРОВАНО (21.06.2026): активные шорт-условия -- 501, 502, 542, 661.**
  Отключены: 503, 504, 541, 642, 641 (641 был источником убытков, см. AUDIT LOG)
- Трёхуровневая система стоп-лосса (разные пороги для spot и futures)
- Две grinding-системы: Grinding v1 (6 уровней) и Grinding v2 (derisk + buyback) --
  механизмы усреднения позиции, основной источник риска при изолированной марже.
  `grinding_enable: true`. Деликатный риск-механизм: добавление позиции при
  приближении к ликвидации (~10%) может ускорить путь к ликвидации, а не защитить
- X7 -- наиболее активно разрабатываемая ветка; X6 считается более стабильной
  для продакшена (по внешним источникам, не подтверждено для нашей версии)
- **Protections заданы в `.py` как class attribute** (не в config.json --
  freqtrade 2026.5.1 хард-эррорит на protections в конфиге): CooldownPeriod
  (6 свечей), StoplossGuard (2 стоплосса в течение 288 свечей, стоп на 288 свечей),
  MaxDrawdown (>10% просадки за 288 свечей, стоп на 288 свечей). Подтверждено в
  `journalctl` обоих деплоев (169dfce и 376627b)
- max_open_trades: 6, stake_amount: unlimited (в live/dry-run конфиге; для
  бэктеста используется fixed-stake оверлей 150 USDT, см. BACKTESTING),
  stoploss: -0.99 (фактически отключён как hard exit, выход через
  ROI/grinding/protections), position_adjustment_enable: True,
  tradable_balance_ratio: 0.99
- **Блэклист:** IDOL и UB добавлены в `blacklist-binance.json` (25.06.2026).
  Причина: грайндинг открыл позиции в этих парах с глубокими убытками во время
  dry-run; оба токена проходят все фильтры пейрлиста (AgeFilter, VolumeFilter) как
  устоявшиеся токены с временно высоким объёмом -- не новые листинги.
  Широкий блэклист (23 пары) тестировался и ухудшал бэктест -- выбран таргетированный подход.

---

## KEY FILES

    Локально: C:\TradingBots\NFI\
    Сервер:   /home/ubuntu/NFI\

      user_data\
        config.json                основной конфиг -- пары, leverage (зашит в .py),
                                    stake, protections (зашиты в .py)
                                    (add_config_files -- относительные имена файлов,
                                    без префикса user_data/)
        blacklist-binance.json     блэклист пар (подключён через add_config_files).
                                    Содержит IDOL/USDT и UB/USDT (добавлены 25.06.2026)
        exampleconfig.json         содержит `dry_run_wallet` (1000 USDT) --
                                    НЕ строгий JSON (есть `//`-комментарии), править
                                    только через текстовый -replace
        config-private.json        секреты (НЕ в git, перенесён вручную через scp)
        pairlist-static-backtest.json  локальный, НЕ в git -- статический снимок
                                    80 пар для бэктеста (через `test-pairlist`)
        backtest-fixed-stake.json  локальный, НЕ в git -- оверлей
                                    `{"stake_amount": 150}` для фиксированного
                                    стейка в бэктестах (unlimited даёт инфляцию
                                    результата на низколиквидных парах)
        strategies\
          NostalgiaForInfinityX7.py  стратегия v17.4.277. Правки сделаны через явное решение:
                                    (1) protections как class attribute,
                                    (2) short_entry_condition_661_enable: True
                                    (финальный набор шорт-условий)
          NostalgiaForInfinityX7.py.bak  бэкап старой версии (v17.4.261) на сервере.
                                    Удалить когда убедишься в стабильности v17.4.277
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

## LAUNCH (сервер, Ubuntu) -- через systemd

    sudo systemctl start freqtrade-nfi
    sudo systemctl stop freqtrade-nfi
    sudo systemctl restart freqtrade-nfi
    sudo systemctl status freqtrade-nfi
    journalctl -u freqtrade-nfi -n 50 --no-pager
    journalctl -u freqtrade-nfi -f

---

## BACKTESTING

### Обязательный шаг перед любой командой (download-data / backtesting / test-pairlist)

    $env:FREQTRADE__API_SERVER__JWT_SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | % {[char]$_})

Переменная живёт только в текущем окне PowerShell -- задавать один раз на сессию.

### Динамический пейрлист не поддерживается бэктестом

Решение: статический оверлей `user_data/pairlist-static-backtest.json` (80 пар,
снимок через `freqtrade test-pairlist` на 20.06.2026).

### Команды

    cd C:\TradingBots\NFI

    freqtrade backtesting `
      --config user_data/config.json `
      --config user_data/pairlist-static-backtest.json `
      --config user_data/backtest-fixed-stake.json `
      --strategy NostalgiaForInfinityX7 `
      --timerange 20250101-20260620 `
      --timeframe 5m `
      --export trades `
      --breakdown day week month `
      --cache none

### Результаты прогонов (хронология, все на dry_run_wallet/starting balance 1000 USDT,
### timerange 20250101-20260620, статический пайрлист 80 пар, fixed stake 150 USDT)

| Прогон | Шорт-условия | Блэклист | Trades | Total profit % | Sharpe | Sortino | SQN | Max DD | Short side |
|---|---|---|---|---|---|---|---|---|---|
| База | 501/502/542 (дефолт) | нет | 430 | 433.62% | -- | 2.23 | -- | 6.73% | ~0 (4 шорт-сделки) |
| #1 (все условия) | 501-504/541-543/641/642/661 | нет | 1014 | 108.03% | 0.73 | 0.29 | 0.64 | 59.73% | -200.02% (-2000 USDT) |
| #2 | 501/502/542/641/661 | нет | 587 | 388.72% | 5.52 | 1.86 | 6.33 | 10.72% | -7.43% (-74 USDT) |
| #3 ФИНАЛ (reference) | 501/502/542/661 | нет | 488 | 435.33% | 8.68 | 1.56 | 10.93 | 5.27% | +6.64% (+66.4 USDT, 62 сделки) |
| #4 (с блэклистом) | 501/502/542/661 | IDOL+UB | 431 | 385.73% | 7.31 | -- | -- | 5.64% | +34.5 USDT |

**Принятый production-baseline:** прогон #4 (431 сделка, +385.73%, Sharpe 7.31, DD 5.64%).
Прогон #3 сохраняется как reference для сравнения. Снижение показателей #4 vs #3
объясняется в том числе различием пейрлистов (не идентичны), а не только блэклистом.

**Анализ по ENTER TAG STATS (прогон #1):** виноваты конкретно условия 503 (-862 USDT),
642 (-787), 541 (-570), 504 (-332) -- высокий winrate (86-94%) маскирует редкие
катастрофические убытки через liquidation/stop_loss/trailing_stop. 641 (+125) и
661 (+243) были в плюсе на тот момент.

**Анализ по ENTER TAG STATS (прогон #2):** именно 641 стал убыточным в этой
конфигурации (-134.60 USDT, 125 сделок, 7 катастрофических выходов на -1101 USDT
суммарно: force_exit, 2×liquidation, trailing_stop, 3×stop_loss). 661 остался в
плюсе (+10.93 USDT, 57 сделок, 1 крупный stop_loss -254.78).

**Анализ по ENTER TAG STATS (прогон #3, финал):** 661 -- 58 входов, 57 win / 1 loss
(98.3%), +17.012 USDT. Всего 3 убыточные сделки из 488 (теги "1", "120", "661" --
по одной каждой). Exit reason `stop_loss`: 2 выхода, -403.648 USDT суммарно
(avg -80.09% за сделку) -- катастрофический по размеру, но единичный риск-кейс
(грайндинг/добавление позиции у ликвидации), не критичный относительно общего
баланса (5353 USDT), но требует внимания при масштабировании на реальные деньги.

**Решение (шорт-условия):** финальный набор -- 501, 502, 542, 661. Профит на уровне
базы (433.62% -> 435.33%), просадка ниже базы (6.73% -> 5.27%), short-сторона
впервые в плюсе. Закоммичено (376627b), задеплоено на сервер 21.06.2026.

**Решение (блэклист):** IDOL и UB добавлены точечно. Широкий блэклист (23 пары)
тестировался и ухудшал производительность -- отброшен.

ВАЖНО (survivorship bias): статический список пар -- снимок топ-80 по объёму на
20.06.2026, применяется ко всему периоду 2025-2026 -- держать в уме при
интерпретации цифр.

---

## LOG WORKFLOW

Локально:

    Get-Content "C:\TradingBots\NFI\user_data\logs\freqtrade.log" | Select-Object -Last 50

На сервере:

    journalctl -u freqtrade-nfi -n 50 --no-pager

---

## KNOWN ISSUES (не переоткрывать)

- UnicodeEncodeError в консоли (локально, Windows) -- emoji в strategy_msg, не
  влияет на торговлю, игнорировать
- На сервере venv-папка `.venv` (не `venv`), пользователь `root` (не `ubuntu`,
  несмотря на путь `/home/ubuntu/NFI`)
- Systemd требует явный `EnvironmentFile=` -- иначе падает на пустом
  `jwt_secret_key`
- Локально та же проблема с пустым `jwt_secret_key` -- лечится через
  `$env:FREQTRADE__API_SERVER__JWT_SECRET_KEY` на сессию PowerShell (не
  персистентно между сессиями)
- Бэктест/download-data не работают с динамическим пейрлистом -- нужен
  статический оверлей (`pairlist-static-backtest.json`)
- `exampleconfig.json` содержит `//`-комментарии -- править только текстовым
  `-replace`, не JSON-парсингом
- `git pull` на сервере может конфликтовать с локальными незакоммиченными
  правками -- всегда проверять `git status`/`git diff` перед pull
- `stake_amount: unlimited` в бэктесте даёт инфляцию результата (+9240% в одном
  из ранних прогонов) на низколиквидных парах -- использовать fixed-stake оверлей
  для интерпретируемых результатов
- **Реальный баланс (1500 USDT) не совпадает с балансом всех проведённых
  бэктестов и текущего dry-run (1000 USDT)** -- при текущих fixed
  max_open_trades=6 / stake=150 это означает больше свободного буфера на
  реальном балансе, чем тестировалось; пересчёт stake/max_open_trades под 1500
  USDT не делался, отдельное решение
- IDOL #3 и UB #5 открыты в dry-run с глубокими убытками (грайндинг) -- новых
  входов в эти пары не будет (блэклист), позиции закроются по стратегии

---

## ROADMAP

| Шаг | Статус |
|-----|--------|
| STEP 1: Установка и настройка | DONE |
| STEP 2: Наблюдение dry_run 1-2 недели | IN PROGRESS (накопление с 21.06.2026 01:13 CEST, баланс 1000 USDT, стратегия v17.4.277 с 25.06.2026) |
| STEP 3: Бэктест на исторических данных | DONE (4 прогона: шорт-условия + блэклист, финальный production-baseline -- #4 с IDOL/UB блэклистом) |
| STEP 4: Оптимизация (Hyperopt) | NOT STARTED |
| STEP 5: Реальная торговля (API ключи + dry_run=false) | NOT STARTED |
| STEP 6: Масштабирование + Telegram + VPS | DONE |
| STEP 7: FreqAI | дальняя цель |

---

## NEXT STEP

Продолжать наблюдение dry-run (v17.4.277, блэклист IDOL/UB, шорт-условия 501/502/542/661).
Параллельно -- решить открытые пункты из PENDING (баланс 1500 vs 1000, порт 8080).

---

## PENDING

- IDOL #3 и UB #5 всё ещё открыты в dry-run -- закроются сами по стратегии,
  мониторить; новых входов не будет (блэклист)
- Реальный баланс 1500 USDT vs тестовый/dry-run баланс 1000 USDT -- решить,
  пересчитывать ли stake_amount/max_open_trades под фактический баланс перед
  переходом к реальной торговле
- Эксперименты с таймфреймами -- пользователь спрашивал о возможности; объяснено,
  что base timeframe и informative timeframes зашиты в `.py`, смена -- отдельное
  явное решение (не лёгкий A/B-тест), конкретная цель эксперимента пока не
  сформулирована
- Информативные таймфреймы NFI X7 (15m/1h/4h/1d) -- предположение по опыту
  сообщества, не сверено с фактическим кодом `.py`
- exchange.key/secret для боевого режима -- STEP 5, пока не трогаем
- Telegram-уведомления выключены (`telegram.enabled: false`) -- решить, включать ли
- `tradesv3.dryrun.sqlite*` на сервере -- untracked в git, добавить в `.gitignore`
- Безопасность FreqUI: порт 8080 открыт на 0.0.0.0 извне -- ограничить firewall'ом
- FreqUI install на сервере (`freqtrade install-ui`) -- статус выполнения не
  подтверждён
- Удалить `.bak` файл на сервере (`user_data/strategies/NostalgiaForInfinityX7.py.bak`)
  когда убедишься в стабильности v17.4.277
- survivorship bias в бэктестах (статический снимок пар на 20.06.2026,
  применяется ко всему периоду 2025-2026)
- Catastrophic stop_loss exits (2 случая, -403.648 USDT суммарно в прогоне #3) --
  единичный риск-кейс грайндинга у ликвидации, не критично сейчас, но требует
  внимания при масштабировании на реальные деньги

---

## AUDIT LOG

| Date       | Status | Notes                                                    |
|------------|--------|------------------------------------------------------------|
| 2026-06-20 | INIT   | Проект выделен из общего чата. Baseline зафиксирован со слов пользователя, файлы стратегии и config.json ещё не получены. |
| 2026-06-20 | UPDATE | Деплой на Ubuntu-сервер: GitHub-репо создан и запушен, freqtrade переустановлен, секреты перенесены через scp, пути в config.json переведены на относительные. |
| 2026-06-20 | UPDATE | config.json поправлен (699c8e1), бот запущен на сервере как systemd-сервис freqtrade-nfi (фиксы User=root, .venv путь, EnvironmentFile=.env), чистый старт подтверждён. STEP 6 закрыт. |
| 2026-06-20 | UPDATE | Подготовка к бэктесту: решён конфликт jwt_secret_key (env var), решена несовместимость динамического пейрлиста с бэктестом (статический оверлей). dry_run_wallet изменён 10000->1000 (локально и на сервере, через git push/pull + git restore при конфликте). Первый прогон бэктеста запущен. |
| 2026-06-20 | UPDATE | Protections добавлены как class attribute в .py (CooldownPeriod 6 свечей, StoplossGuard 2/288, MaxDrawdown 10%/288) -- freqtrade 2026.5.1 блокирует protections в config.json. Закоммичено (169dfce), задеплоено, подтверждено в journalctl. |
| 2026-06-21 | UPDATE | Разобрана причина малого числа шортов (4 из 430): из ~11 условий реализовано 9 + дохлый флаг 603, по умолчанию активны только 501/502/542. Прогон со всеми условиями (1014 trades, +108.03%, DD 59.73%, short -200.02%) -- резкое ухудшение. Анализ по тегам выявил виновников: 503/642/541/504 (катастрофические редкие убытки при высоком winrate). Прогон с 501/502/542/641/661 (587 trades, +388.72%, DD 10.72%, short -7.43%) -- лучше, но short всё ещё в минусе; повторный анализ по тегам выявил 641 как остаточную проблему (-134.60 USDT, liquidation/stop_loss). |
| 2026-06-21 | UPDATE | Финальный прогон с 501/502/542/661 (488 trades, +435.33%, Sharpe 8.68, Sortino 1.56, Calmar 296.43, SQN 10.93, DD 5.27%, short +66.4 USDT) -- профит на уровне базы, просадка ниже базы, short впервые в плюсе. Решение зафиксировано, правка .py закоммичена (376627b), задеплоена на сервер 21.06.2026. |
| 2026-06-25 | UPDATE | Добавлен блэклист IDOL+UB в blacklist-binance.json (таргетированный фикс; широкий блэклист 23 пар тестировался и ухудшал бэктест). Бэктест #4 с блэклистом: 431 сделка, +385.73%, Sharpe 7.31, DD 5.64% -- принят как production-baseline. Стратегия обновлена v17.4.261 -> v17.4.277 ("fine tune the grind entries"), наши правки (protections + шорт-условия) перенесены в новый файл, бэкап старого -- .py.bak на сервере. Всё закоммичено (227d07d), задеплоено, бот RUNNING. IDOL #3 и UB #5 остаются открытыми, закроются по стратегии. |

---
*End of SYSTEM_KNOWLEDGE.md*
