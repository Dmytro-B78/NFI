# ANCHOR_LOG.md

Единый файл фиксированных anchor-прогонов для A/B-бэктестов. Один активный
anchor на текущий пейрлист-снимок; при смене снимка или коде-baseline --
старая запись помечается SUPERSEDED, новая добавляется сверху.

**Правило переиспользования:** candidate обязан использовать тот же файл
пейрлист-снимка и тот же timerange, что указаны в активной записи. Если
снимок или timerange отличаются -- anchor невалиден для сравнения, гонится
заново.

**Правило обновления:** новая запись фиксируется только в двух случаях --
(1) деплой новой code-baseline, (2) генерация нового пейрлист-снимка.

---

## ACTIVE

**Дата фиксации:** 2026-07-30
**Код (наш):** v17.4.434, commit `b03b90a`
**Код (апстрим):** commit `0fa0a1a` ("system_v3_2: fine tune the grind entries")
**Пейрлист-снимок:** `pairlist-static-backtest-derisk4.json` (79 пар -- top-80
через `VolumePairList`, минус блэклист после расширения на 25 тикеров
токенизированных TradFi-акций/товаров, commit `160f3e4`, 30.07.2026;
соответствует боевому пейрлисту)
**Timerange:** 2025-01-03 18:40:00 -- 2026-07-24 00:00:00 (запрошено
20250101-20260724)
**Результаты:** `backtest_anchor_v434_derisk4_full.log`

| Метрика | Значение |
|---|---|
| Trades | 484 |
| Total profit | 3 876.863 USDT (387.69%) |
| CAGR | 177.82% |
| Sharpe (closed trades) | 12.25 |
| Sortino (closed trades) | 4.74 |
| Calmar (closed trades) | 758.06 |
| SQN | 16.48 |
| Profit factor | 46.26 |
| Expectancy (Ratio) | 8.01 (0.19) |
| Worst day | -85.667 USDT |
| Max % underwater (closed trades) | 1.73% |
| Max % underwater (wallet balance) | 3.73% |
| Long / Short trades | 376 / 108 |
| Long / Short profit | 363.38% / 24.31% |
| Worst trade | ERA/USDT:USDT -20.30% |

---

## SUPERSEDED

### 2026-07-30 -- заменён (пейрлист-снимок устарел: блэклист расширен на 25
тикеров токенизированных TradFi-акций/товаров, commit `160f3e4`, 30.07.2026 --
снимок derisk3 больше не соответствует боевому пейрлисту)

**Код (наш):** v17.4.434, commit `b03b90a`
**Код (апстрим):** commit `0fa0a1a`
**Пейрлист-снимок:** `pairlist-static-backtest-derisk3.json` (78 пар)
**Timerange:** 2025-01-03 18:40:00 -- 2026-07-24 00:00:00 (запрошено
20250101-20260724)
**Результаты:** `backtest_anchor_v434_80pairs_full.log`

| Метрика | Значение |
|---|---|
| Trades | 415 |
| Total profit | 3 326.817 USDT (332.68%) |
| CAGR | 157.19% |
| Sharpe (closed trades) | 10.43 |
| Sortino (closed trades) | 4.07 |
| Calmar (closed trades) | 578.40 |
| SQN | 15.14 |
| Profit factor | 39.83 |
| Expectancy (Ratio) | 8.02 (0.19) |
| Worst day | -85.667 USDT |
| Max % underwater (closed trades) | 1.94% |
| Max % underwater (wallet balance) | 4.02% |
| Long / Short trades | 322 / 93 |
| Long / Short profit | 313.35% / 19.33% |
| Worst trade | ERA/USDT:USDT -20.30% |

### 2026-07-28 -- заменён (снимок 120 пар не соответствовал боевому пейрлисту
после отката 120->80, commit `ca10153`)

**Код (наш):** v17.4.434, commit `b03b90a`
**Код (апстрим):** commit `0fa0a1a`
**Пейрлист-снимок:** `pairlist-static-backtest-derisk2.json` (120 пар)
**Timerange:** 20250101-20260724
**Результаты:** `backtest_v434_candidate_full.log`

| Метрика | Значение |
|---|---|
| Trades | 618 |
| Total profit | 210 184 USDT |
| Sharpe | 10.23 |
| Sortino | 5.41 |
| Calmar | 23 383 |
| SQN | 12.18 |
| Profit factor | 32.84 |
| Expectancy | 340.10 |
| Worst day | -1 060.06 USDT |
| Max % underwater | 3.03% |