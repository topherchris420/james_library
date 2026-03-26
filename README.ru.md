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

## Быстрый старт

```bash
python rain_lab.py
```

Подробности по командам и конфигурации доступны в docs-хабе и справочных разделах.

## Возможности в одном месте (Capabilities At A Glance)

Эта страница — входная точка. Для полного покрытия runtime-поверхности (команды, каналы, провайдеры, эксплуатация, безопасность, железо) используйте ссылки ниже.

| Область возможностей | Что доступно | Канонический справочник |
| --- | --- | --- |
| CLI и автоматизация | Онбординг, agent, gateway/daemon, service, диагностика, estop, cron, skills, обновления | [Commands Reference](docs/reference/cli/commands-reference.md) |
| Каналы и сообщения | Мультиканальная доставка, allowlists, режимы webhook/polling, конфиг по каналам | [Channels Reference](docs/reference/api/channels-reference.md) |
| Провайдеры и маршрутизация моделей | Локальные/облачные провайдеры, алиасы, env-переменные авторизации, обновление моделей | [Providers Reference](docs/reference/api/providers-reference.md) |
| Конфигурация и runtime-контракты | Схема конфигурации и поведенческие гарантии | [Config Reference](docs/reference/api/config-reference.md) |
| Эксплуатация и диагностика | Runbook, паттерны деплоя, диагностика и восстановление после сбоев | [Operations Runbook](docs/ops/operations-runbook.md), [Troubleshooting](docs/ops/troubleshooting.md) |
| Модель безопасности | Песочница, границы политик, аудит | [Security Docs Hub](docs/security/README.md) |
| Оборудование и периферия | Настройка плат и дизайн инструментов периферии | [Hardware Docs Hub](docs/hardware/README.md) |

## Что читать дальше по роли (Who Should Read What Next)

- **Новые пользователи / первый запуск**: начните с [`START_HERE.md`](START_HERE.md), затем перейдите к [`docs/getting-started/README.md`](docs/getting-started/README.md).
- **Операторы / владельцы деплоя**: в первую очередь [`docs/ops/operations-runbook.md`](docs/ops/operations-runbook.md) и [`docs/ops/troubleshooting.md`](docs/ops/troubleshooting.md).
- **Интеграторы / разработчики расширений**: в первую очередь [`docs/reference/cli/commands-reference.md`](docs/reference/cli/commands-reference.md), [`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md), [`docs/reference/api/providers-reference.md`](docs/reference/api/providers-reference.md), [`docs/reference/api/channels-reference.md`](docs/reference/api/channels-reference.md).
