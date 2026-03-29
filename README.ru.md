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
