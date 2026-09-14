FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8506
CMD ["gunicorn", "--bind", "0.0.0.0:8506", "--workers", "2", "app.main:app"]
