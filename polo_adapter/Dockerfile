FROM python:3.11-slim

WORKDIR /app

COPY polo_adapter/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY polo_adapter /app/polo_adapter

EXPOSE 8010

CMD ["python", "-m", "polo_adapter.app.main"]
