# NOT TESTED in the build environment (no Docker available there). Review before relying on it.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["sh", "-c", "alembic upgrade head && streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
