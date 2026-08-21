FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV GO_HOST=0.0.0.0
ENV GO_PORT=8000
ENV GO_CORS_ORIGINS=*
ENV GO_MCTS_SIMS=500

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
