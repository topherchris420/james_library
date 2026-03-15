# Точка входа в документацию R.A.I.N. Lab (RU)

> Эта страница — русскоязычная точка входа, синхронизированная с основной структурой README и docs.

## Навигация

- Основной README: [`README.md`](README.md)
- Хаб документации (RU): [`docs/README.ru.md`](docs/README.ru.md)
- Единое оглавление: [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Быстрая карта проекта

- **R.A.I.N. Lab**: продуктовый интерфейс для конечного пользователя
- **James Library**: Python-слой исследований и workflow
- **ZeroClaw**: Rust-слой рантайма (crate `zeroclaw`)

Поток выполнения: `Пользователь -> интерфейс R.A.I.N. Lab -> рантайм ZeroClaw -> исследовательские workflow James Library -> API моделей/провайдеров`

## Быстрый старт

```bash
python rain_lab.py
```

Подробности по командам и конфигурации доступны в docs-хабе и справочных разделах.
