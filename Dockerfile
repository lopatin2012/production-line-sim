FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY printer_sim ./printer_sim

RUN pip install --no-cache-dir ".[opcua,s7]"

ENV PYTHONUNBUFFERED=1

EXPOSE 9100 9101 9102 9200 502 4840 102

ENTRYPOINT ["python", "-m", "printer_sim"]
CMD ["--host", "0.0.0.0", "--control-host", "0.0.0.0", "--printers", "3", "--base-port", "9100", "--control-port", "9200", "--modbus-host", "0.0.0.0", "--modbus-port", "502", "--opcua-host", "0.0.0.0", "--opcua-port", "4840", "--s7-host", "0.0.0.0", "--s7-port", "102"]
