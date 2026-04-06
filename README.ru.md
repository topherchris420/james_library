# Точка входа в документацию R.A.I.N. Lab (RU)

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> Эта страница — русскоязычная точка входа, синхронизированная с основной структурой README и docs.

## Навигация

- Основной README: [`README.md`](README.md)
- Хаб документации (RU): [`docs/README.ru.md`](docs/README.ru.md)
- Единое оглавление: [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Быстрая карта проекта

- **R.A.I.N. Lab**: продуктовый интерфейс для конечного пользователя
- **James Library**: Python-слой исследований и workflow
- **R.A.I.N.**: Rust-слой рантайма (crate `R.A.I.N.`)

Поток выполнения: `Пользователь -> интерфейс R.A.I.N. Lab -> рантайм R.A.I.N. -> исследовательские workflow James Library -> API моделей/провайдеров`

## Полные возможности James

James — это не просто мультиагентный чат, а полноценная исследовательская операционная система: 10+ провайдеров моделей, 25+ платформ обмена сообщениями, 60+ встроенных инструментов, управление оборудованием (Arduino, STM32, Raspberry Pi), нейронаучная модель кодирования мозга (TRIBE v2), граф знаний, семантическая память и многое другое. Полный список — в английском [`README.md` - What You Can Do](README.md#what-you-can-do).

## Для кого это

R.A.I.N. Lab создан для людей, которым нужны ответы, которые можно обосновать, а не просто ответы, которые хорошо звучат.

| Роль | Что можно делать с R.A.I.N. Lab |
| --- | --- |
| Основатели и продуктовые лидеры | Стресс-тестировать стратегические решения с помощью структурированных дебатов до утверждения дорожной карты или бюджета |
| Исследователи и аналитики | Сравнивать конкурирующие гипотезы, сохранять разногласия и фиксировать проверяемые цепочки рассуждений |
| Операторы и технические команды | Превращать хаотичные обсуждения в верифицируемые результаты, которые можно проверить, передать и воспроизвести |

На практике это означает меньше тупиков вида «ИИ так сказал». Вы можете начать с одного вопроса, позволить нескольким агентам проверить допущения, направить неразрешённые конфликты через верификацию и получить результат, который можно уверенно представить другим людям.

## Быстрый старт

```bash
python rain_lab.py
```

Подробности по командам и конфигурации доступны в docs-хабе и справочных разделах.

## Как это выглядит в действии

Задайте сырой исследовательский вопрос. Наблюдайте, как четыре экспертных агента — James (ведущий учёный), Jasmine (постдок-скептик), Luca (геометр) и Elena (логик) — обсуждают его в реальном времени.

```
TOPIC: Could a "Phononic Morphogenetic Field" — precise acoustic interference patterns
guiding matter assembly like DNA guides cell growth — actually work?

**James:** ...phononic frequency combs could act like an acoustic blueprint for
molecular organization. The missing link between quantum coherence and biological
assembly?

**Jasmine:** Hold on. Cymatic patterns are *static* — they don't adapt to errors
or material changes the way DNA does. And the energy density needed exceeds
current acoustic levitation by *orders of magnitude*. Where's the thermal
dissipation analysis?

**Luca:** The geometry is compelling though. Wavelength spacing in phononic
combs (ωₙ₊₁ - ωₙ = 2πc/λ) parallels scalar field gradients in relic field
tomography. But macroscopic assembly requires E > 10⁴⁵ J — far beyond reach.

**Elena:** The math is elegant but the premise has a fatal flaw. The energy
density violates the Landauer limit by multiple orders of magnitude. Current
systems operate ~10³ times lower. Without experimental validation at that
scale, this remains speculation.

[Meeting continues — James responds, Jasmine pushes back, consensus forms...]
```

Присоединяйтесь к исследовательской встрече, изучайте разногласия и уходите с планом следующих шагов — а не просто со ссылками.

---

## Качество результата и доверие

### Качество результата (по бенчмаркам)

R.A.I.N. Lab отслеживает инженерное качество в CI и публикует явные определения метрик, базовые уровни и целевые значения (например: количество panic, количество unwrap, доля flaky-тестов и покрытие критического пути).

- Контракт метрик качества: [`docs/project/quality-metrics.md`](docs/project/quality-metrics.md)
- Генератор отчёта по качеству: [`scripts/ci/quality_metrics_report.py`](scripts/ci/quality_metrics_report.py)

Для оценки исследовательских результатов мы рекомендуем публиковать воспроизводимые артефакты до/после (набор задач, baseline, rubric и файлы результатов) вместе с этими отчётами качества.

### Доверие + приватность

R.A.I.N. Lab спроектирован как local-first и использует безопасные настройки по умолчанию:

- локальные/приватные сценарии работы и маршрутизация на локальные модели
- gateway по умолчанию слушает localhost, pairing включён, публичный bind отключён
- доступ к каналам по allowlist с deny-by-default политикой
- секреты высокой ценности хранятся в encrypted-at-rest виде

Документация по текущему поведению безопасности:

- [`docs/security/README.md`](docs/security/README.md)
- [`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)
