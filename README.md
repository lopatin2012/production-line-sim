# production-line-sim

Симулятор производственного участка: виртуальная линия с принтерами, датчиками,
аппликатором, камерой, сканером и отводом брака. Позволяет разрабатывать,
демонстрировать и тестировать конвейер без реального железа: движок гоняет
«изделия» по линии, устройство печатает по ZPL, есть HMI, теги с адресами и шина
событий. Пакет не имеет внешних зависимостей (только стандартная библиотека
Python 3.12+).

## Возможности

- **Линия**: конвейер, датчики, принтеры, аппликатор, камера, сканер/верификация,
  отвод брака, накопитель; генерация изделий, счётчики, аварии (замятие, отказ
  сканера), смена продукта.
- **Принтеры Zebra/TSC** по сырому сокету (порт 9100 и далее): ответы на
  `~HI` (модель, прошивка, dpi, память), `~HS` (флаги бумаги/риббона/головки,
  режим печати, этикетки в задании), `~HQES` (ошибки, износ головки).
- **HMI**: анимированная схема линии, кнопки оператора, тумблеры неисправностей,
  лента событий, карта тегов.
- **Теги АСУТП** с адресами (coils / discrete inputs / holding / input registers) —
  база для протоколов ПЛК.
- **Шина событий** (`changeover`, `print`, `verify_fail`, `reject`, `jam`, …) —
  внешние программы могут реагировать на события линии.
- Учёт напечатанного (этикетки, длина печати), инъекция неисправностей, сброс.
- Конфигурация через JSON/CLI, несколько принтеров в одном процессе.

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

## Веб-интерфейс

Откройте `http://127.0.0.1:9200/` — HMI линии: анимированная схема (изделия едут,
датчики и устройства подсвечиваются), кнопки Пуск/Стоп/Замятие/Сброс, выбор
продукта и «Смена продукта», скорость, счётчики, лента событий, тумблеры
неисправностей принтеров и карта тегов. Обновляется автоматически.

## Control API

По умолчанию `http://127.0.0.1:9200`. `GET /` и `GET /ui` отдают HMI,
`GET /health` — JSON.

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/line/state` | состояние линии (станции, изделия, счётчики) |
| POST | `/line/control` | действие: `{"action":"start\|stop\|jam\|clear\|scanner_fault\|speed\|changeover", ...}` |
| GET | `/events?after=&limit=` | лента событий (для реакции внешних программ) |
| GET | `/tags` | карта тегов с адресами |
| POST | `/tags` | записать тег: `{"name":"line.speed","value":0.3}` |
| GET | `/printers` | список принтеров |
| GET | `/state` | состояние всех принтеров |
| GET | `/printers/{name}` | состояние принтера |
| POST | `/printers/{name}/faults` | задать неисправности (JSON) |
| POST | `/printers/{name}/config` | изменить модель/прошивку/dpi и пр. |
| POST | `/printers/{name}/reset` | сбросить флаги и счётчики |
| POST | `/printers/{name}/print` | «напечатать» N этикеток: `{"quantity": 10}` |

Пример:

```bash
curl -X POST http://127.0.0.1:9200/line/control \
  -H "Content-Type: application/json" -d '{"action":"start"}'
curl -X POST http://127.0.0.1:9200/line/control \
  -H "Content-Type: application/json" -d '{"action":"changeover","product":"Кефир 0,5 л"}'
curl http://127.0.0.1:9200/events | head
curl -X POST http://127.0.0.1:9200/printers/sim-1/faults \
  -H "Content-Type: application/json" -d '{"paper_out": true}'
```

## Modbus TCP

Шлюз отдаёт теги по стандартным таблицам (unit id 1, порт по умолчанию `502`
в образе, `5020` при локальном запуске):

| Теги | Таблица | Адреса |
| --- | --- | --- |
| bool `rw` (команды: `line.start`, `line.jam`, `line.changeover`, …) | coils | 00001+ |
| bool `ro` (`line.running`, `line.jam_state`, `.active`, `printer.*.fault`) | discrete inputs | 10001+ |
| int/real/str `rw` (`line.speed`, …) | holding registers | 40001+ |
| int/real/str `ro` (`line.produced`, `line.product`, …) | input registers | 30001+ |

`real` занимает 2 регистра (IEEE-754, big-endian), `str` — блок 16 регистров
(UTF-8). Команды пишутся в coils/registers и применяются движком на следующем тике.

Пример на Python (`pip install pymodbus`):

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("127.0.0.1", port=502)
client.connect()
client.write_coil(0, True)                 # line.start
print(client.read_discrete_inputs(0, 1))   # line.running
print(client.read_input_registers(0, 1))   # line.produced
client.close()
```

## Soft-PLC

Встроенный движок логики поверх тех же тегов, что и Modbus. Правило — это
`when` (условия по тегам, объединяются по AND) и `then` (действия). Действия:
`{"set": "тег", "value": ...}` и `{"control": "start|stop|jam|clear|scanner_fault|speed|changeover", ...}`.
`"edge": true` — срабатывание по фронту (иначе уровень). Пример —
`plc_rules.example.json`.

```bash
python -m printer_sim --plc-file plc_rules.example.json
```

```bash
curl http://127.0.0.1:9200/plc
curl -X POST http://127.0.0.1:9200/plc/rules -H "Content-Type: application/json" \
  -d '{"rule":{"name":"jam","when":[{"tag":"line.produced","op":">=","value":3}],"then":[{"set":"line.jam","value":true}]}}'
curl -X POST http://127.0.0.1:9200/plc/enable -H "Content-Type: application/json" -d '{"enabled":false}'
curl -X DELETE http://127.0.0.1:9200/plc/rules/jam
```

В HMI есть панель Soft-PLC: включение, редактирование правил (JSON), кнопка
«Пример», счётчики срабатываний.

## Roadmap АСУТП

- [x] Модель линии, движок, теги, события, HMI.
- [x] **Modbus TCP** — шлюз «теги ↔ coils/registers», подключение ПЛК/OpenPLC.
- [x] **Soft-PLC** — встроенный движок логики (правила) поверх тегов.
- [ ] **OPC UA** (`asyncua`), **EtherNet/IP** (`pycomm3`/`cpppo`), **S7** (`snap7`).
- [ ] Смена продукта как событие для внешних программ (реакция ПЛК/SCADA).

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
