FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir -c requirements.lock .
EXPOSE 8000
CMD ["uvicorn", "job_hunter.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
