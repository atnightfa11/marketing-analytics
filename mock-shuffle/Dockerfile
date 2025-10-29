FROM python:3.12-slim
WORKDIR /app
COPY main.py .
RUN pip install --no-cache-dir fastapi uvicorn httpx
EXPOSE 8787
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
