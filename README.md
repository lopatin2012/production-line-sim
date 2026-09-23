# production-line-sim

Симулятор производственной линии: виртуальные ZPL/TSC-принтеры этикеток с
управляющим HTTP-API. Позволяет разрабатывать, демонстрировать и тестировать
конвейер печати без реального железа:
сервер слушает TCP-порт (по умолчанию 9100), принимает поток ZPL, отвечает на
диагностические команды и умеет имитировать неисправности.

Пакет не имеет внешних зависимостей (только стандартная библиотека Python 3.12+).

## Возможности

- TCP-сервер на каждый принтер (порт 9100 и далее), совместим с драйверами
  Zebra/TSC по сырому сокету.
- Ответы на ZPL-команды:
  - `~HI` — модель, версия ПО, dots/mm, память, опции;
  - `~HS` — флаги: нет бумаги, пауза, головка поднята, нет риббона, буфер полон,
    режим печати, число этикеток в задании, длина этикетки;
  - `~HQES` — битфилды ошибок и предупреждений (включая износ печатающей головки).
- Учёт напечатанного: число этикеток и суммарная длина печати (наработка).
- Инъекция неисправностей и сброс через HTTP control API.
- Конфигурация через JSON или CLI, запуск нескольких принтеров в одном процессе.

## Запуск

```bash
python -m printer_sim --printers 3 --base-port 9100 --control-port 9200
```

Из конфигурации:

```bash
python -m printer_sim --config config.example.json
```

Docker:

```bash
docker build -t production-line-sim .
docker run --rm -p 9100-9102:9100-9102 -p 9200:9200 production-line-sim
```

## Control API

По умолчанию `http://127.0.0.1:9200`.

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/health` | проверка живости |
| GET | `/printers` | список принтеров |
| GET | `/state` | состояние всех принтеров |
| GET | `/printers/{name}` | состояние принтера |
| POST | `/printers/{name}/faults` | задать неисправности (JSON) |
| POST | `/printers/{name}/config` | изменить модель/прошивку/dpi и пр. |
| POST | `/printers/{name}/reset` | сбросить флаги и счётчики |
| POST | `/printers/{name}/print` | «напечатать» N этикеток: `{"quantity": 10}` |

Пример:

```bash
curl -X POST http://127.0.0.1:9200/printers/sim-1/faults \
  -H "Content-Type: application/json" \
  -d '{"paper_out": true, "bad_head_elements": true}'
curl http://127.0.0.1:9200/printers/sim-1
curl -X POST http://127.0.0.1:9200/printers/sim-1/reset
```

## Образ

GHCR: `ghcr.io/lopatin2012/production-line-sim:latest` — публикуется CI при push
в `main` и по тегам.

## Связь с ядром

Проект развивается независимо от ядра Etiketron. Ядро подключает симулятор
образом в `docker-compose.playground.yml`; при изменении протокола ядро и
симулятор обновляются отдельными релизами и фиксируются тегом/версией.

## Тесты

```bash
pip install pytest pytest-asyncio
python -m pytest -q
```

## Лицензия

MIT, см. `LICENSE`.
