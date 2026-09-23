FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY printer_sim ./printer_sim

ENV PYTHONUNBUFFERED=1

EXPOSE 9100 9101

ENTRYPOINT ["python", "-m", "printer_sim"]
CMD ["--host", "0.0.0.0", "--control-host", "0.0.0.0", "--printers", "3", "--base-port", "9100", "--control-port", "9200"]
