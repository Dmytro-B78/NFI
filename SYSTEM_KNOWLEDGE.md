# ================================================================
# Freqtrade Futures Bot -- SYSTEM KNOWLEDGE BASE
# Strategy: NostalgiaForInfinityX7
# Audit date: 2026-06-20
# Status: DRY-RUN (план перехода на реальные деньги)
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

---

## PROJECT STATE

| Parameter   | Value                                                          |
|-------------|------------------------------------------------------------------|
| Root        | C:\TradingBots\NFI\                                              |
| Exchange    | Binance Futures (isolated margin)                                |
| Strategy    | NostalgiaForInfinityX7 (community, repo iterativv/NostalgiaForInfinity) |
| Mode        | DRY-RUN -> план Real money                                       |
| Python      | 3.12.10 (venv)                                                   |
| Freqtrade   | 2026.5.1                                                         |
| FreqUI      | http://localhost:8080 (freqtrade / freqtrade123)                 |

Note: версия и дата последнего апдейта стратегии не проверены против upstream --
требует сверки при первом реальном разборе файла.

---

## CONFIRMED BASELINE (2026-06-20, ~137 часов работы)

| Метрика  | Значение         |
|----------|------------------|
| Trades   | 15               |
| WR       | 93%              |
| Profit   | +92.629 USDT     |
| Balance  | 683.129 USDT (dry) |
| Start    | 13.06.2026 22:00 |
| Uptime   | ~137 часов        |

ВАЖНО: 15 сделок -- статистически незначимая выборка. WR=93% не является
подтверждённой эффективностью стратегии с 18 режимами входа. Не использовать
эту цифру как основание для перехода на реальные деньги без бэктеста на
истории и/или накопления значительно большей выборки.

---

## STRATEGY FACTS (общие сведения о NFI X7, не специфика данной установки)

- Седьмая итерация community-стратегии NostalgiaForInfinity (разработчик iterativv)
- Базовый таймфрейм 5m, индикаторы с нескольких старших таймфреймов,
  требует 800 свечей истории для валидных сигналов
- 18 торговых режимов: 10 long + 8 short, разные entry tags, риск-профили,
  размеры позиций и стратегии выхода
- Трёхуровневая система стоп-лосса (разные пороги для spot и futures)
- Две grinding-системы: Grinding v1 (6 уровней) и Grinding v2 (derisk + buyback) --
  механизмы усреднения позиции, основной источник риска при изолированной марже
- X7 -- наиболее активно разрабатываемая ветка; X6 считается более стабильной
  для продакшена (по состоянию на внешние источники, не подтверждено для
  установленной версии)
- В репозитории есть nfi-updater -- сервис автообновления стратегии/blacklist/pairlist;
  не подтверждено, используется ли он в данной установке

---

## KEY FILES (пути из исходного сообщения, содержимое не проверено)

    C:\TradingBots\NFI\
      user_data\
        config.json                основной конфиг -- пары, leverage, stake, protections
        strategies\
          NostalgiaForInfinityX7.py  стратегия -- НЕ редактировать без решения
        logs\
          freqtrade.log

---

## LAUNCH COMMAND

    cd C:\TradingBots\NFI
    venv\Scripts\activate
    chcp 65001; $env:PYTHONIOENCODING="utf-8"; python -m freqtrade trade --config user_data/config.json --strategy NostalgiaForInfinityX7

---

## BACKTESTING COMMAND (для проверки на истории, ещё не запускался)

    freqtrade backtesting `
      --config user_data/config.json `
      --strategy NostalgiaForInfinityX7 `
      --timerange 20250101-20260201 `
      --timeframe 5m `
      --export trades `
      --export-filename backtest_results_nfi_x7 `
      --breakdown day week month `
      --cache none

Не запускалось в рамках этого проекта -- параметры (timerange и т.д.) требуют
согласования перед первым запуском.

---

## LOG WORKFLOW

Всегда фильтровать перед отправкой:

    Get-Content "C:\TradingBots\NFI\user_data\logs\freqtrade.log" | Select-Object -Last 50

При диагностике конкретной проблемы -- grep по паре или ключевому слову ошибки.

---

## KNOWN ISSUES (не переоткрывать)

- UnicodeEncodeError в консоли -- стратегия генерирует emoji в strategy_msg.
  Не влияет на торговлю. Игнорировать.

---

## ROADMAP

| Шаг | Статус |
|-----|--------|
| STEP 1: Установка и настройка | DONE (13.06.2026) |
| STEP 2: Наблюдение dry_run 1-2 недели | IN PROGRESS |
| STEP 3: Бэктест на исторических данных | NOT STARTED |
| STEP 4: Оптимизация (Hyperopt) | NOT STARTED |
| STEP 5: Реальная торговля (API ключи + dry_run=false) | NOT STARTED |
| STEP 6: Масштабирование + Telegram + VPS | NOT STARTED |
| STEP 7: FreqAI | дальняя цель |

---

## NEXT STEP

Получить от пользователя реальный config.json и/или strategies/NostalgiaForInfinityX7.py
для первого разбора внутренней логики: активные пары, leverage, max_open_trades,
stoploss-параметры, какие из 18 режимов входа включены/выключены.

---

## PENDING

- Решить: продолжать dry-run параллельно с backtesting, или сразу переходить
  к историческому тесту
- Сверить версию стратегии (дата последнего коммита) против актуальной на GitHub
  (iterativv/NostalgiaForInfinity)
- После первого реального файла config.json -- обновить этот раздел PROJECT STATE
  актуальными значениями вместо "не проверено"

---

## AUDIT LOG

| Date       | Status | Notes                                                    |
|------------|--------|------------------------------------------------------------|
| 2026-06-20 | INIT   | Проект выделен из общего чата. Baseline зафиксирован со слов пользователя (15 trades, WR 93%, +92.629 USDT), файлы стратегии и config.json ещё не получены. |

---
*End of SYSTEM_KNOWLEDGE.md*