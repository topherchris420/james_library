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

## Обзор возможностей

James — это не просто мультиагентный чат, а полноценная исследовательская операционная система: 10+ провайдеров моделей, 25+ платформ обмена сообщениями, 60+ встроенных инструментов, управление оборудованием (Arduino, STM32, Raspberry Pi), нейронаучная модель кодирования мозга (TRIBE v2), граф знаний, семантическая память и многое другое. Полный список — в английском [`README.md` - What It Does](README.md#what-it-does).

## Для кого это

R.A.I.N. Lab создан для людей, которым нужны ответы, которые можно обосновать, а не просто ответы, которые хорошо звучат.

| Роль | Что можно делать с R.A.I.N. Lab |
| --- | --- |
| Основатели и продуктовые лидеры | Стресс-тестировать стратегические решения с помощью структурированных дебатов до утверждения дорожной карты или бюджета |
| Исследователи и аналитики | Сравнивать конкурирующие гипотезы, сохранять разногласия и фиксировать проверяемые цепочки рассуждений |
| Операторы и технические команды | Превращать хаотичные обсуждения в верифицируемые результаты, которые можно проверить, передать и воспроизвести |

## Чем отличается

| Типичный исследовательский инструмент | R.A.I.N. Lab |
| --- | --- |
| Возвращает список статей | Возвращает дебаты |
| Считает первый правдоподобный ответ правильным | Сохраняет разногласия до появления доказательств |
| Одна точка зрения, одна модель | Четыре голоса с разной экспертизой и ограничениями |
| Cloud-first | Полностью работает локально |

## Локальный и приватный рабочий процесс

R.A.I.N. Lab полностью работает на вашем оборудовании. Подключите локальную модель через [LM Studio](https://lmstudio.ai/) или [Ollama](https://ollama.com/) — никаких облачных вызовов, телеметрии или передачи данных.

## Быстрый старт

**Онлайн-демо:** [rainlabteam.vercel.app](https://rainlabteam.vercel.app/) — установка не требуется

```bash
python rain_lab.py
```

Windows: дважды нажмите на `INSTALL_RAIN.cmd`.
macOS/Linux: запустите `./install.sh`.

Подробности по командам и конфигурации доступны в docs-хабе и справочных разделах.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или pip
- Rust toolchain (опционально, для слоя рантайма ZeroClaw)
- Локальная модель через [LM Studio](https://lmstudio.ai/) или [Ollama](https://ollama.com/) (опционально — демо-режим работает без неё)

## Документация

| | |
|---|---|
| **Начало работы** | [Начните здесь](START_HERE.md) -- [Руководство для начинающих](docs/getting-started/README.md) -- [Установка в один клик](docs/one-click-bootstrap.md) -- [Устранение неполадок](docs/troubleshooting.md) |
| **Статьи** | [Архив исследований](https://topherchris420.github.io/research/) |
| **Другие языки** | [English](README.md) -- [简体中文](README.zh-CN.md) -- [日本語](README.ja.md) -- [Français](README.fr.md) -- [Tiếng Việt](README.vi.md) |

## Для разработчиков

Архитектура, точки расширения и порядок внесения вклада описаны в английском [`README.md` - For Developers](README.md#for-developers), [ARCHITECTURE.md](ARCHITECTURE.md) и [CLAUDE.md](CLAUDE.md).

## Благодарности

Особая благодарность команде **ZeroClaw** за Rust-движок рантайма, который лежит в основе R.A.I.N. Lab. Подробности — в каталоге `crates/`.

---

**Лицензия:** MIT -- [Vers3Dynamics](https://vers3dynamics.com/)
