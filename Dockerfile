FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m club && mkdir /data && chown club /data
COPY server.py sync.py ./
COPY dist ./dist
USER club
ENV DATABASE_PATH=/data/club.db
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "90", "server:application"]
