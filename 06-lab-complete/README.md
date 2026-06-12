# Lab 12 - Complete Production Agent

This folder contains the finished Day 12 production-ready AI agent.

## Deliverable Checklist

- [x] REST API agent endpoint
- [x] Conversation history
- [x] Redis-backed stateless design
- [x] API key authentication
- [x] Rate limiting: 10 requests/minute per user
- [x] Cost guard: $10/month per user
- [x] Health check: `GET /health`
- [x] Readiness check: `GET /ready`
- [x] Structured JSON logging
- [x] Graceful shutdown handling
- [x] Multi-stage Dockerfile
- [x] Docker Compose stack with Nginx load balancer, scalable agent, and Redis
- [x] Railway and Render deployment config

## Structure

```text
06-lab-complete/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── auth.py
│   ├── rate_limiter.py
│   ├── cost_guard.py
│   ├── storage.py
│   └── llm.py
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── railway.toml
├── render.yaml
├── .env.example
├── .dockerignore
└── requirements.txt
```

## Run Locally

```bash
docker compose up --scale agent=3
```

Test through Nginx:

```bash
curl http://localhost/health
curl http://localhost/ready

curl -H "X-API-Key: secret" \
     -X POST http://localhost/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What is deployment?", "user_id": "user1"}'

curl -H "X-API-Key: secret" http://localhost/history/user1
```

## Production Readiness Check

```bash
python check_production_ready.py
```

The checker verifies required files, security basics, endpoints, Docker hardening, health checks, and structured logging.

## Verified Results

- `python check_production_ready.py`: 20/20 checks passed.
- `docker build -t day12-lab-complete:latest .`: passed.
- Final Docker image size: 247 MB, below the 500 MB requirement.
- `docker compose up -d --build --scale agent=3`: passed with 3 healthy agent containers, healthy Redis, and Nginx on port 80.
- Nginx smoke tests passed: `/health` 200, `/ready` 200, missing auth 401, authenticated `/ask` 200, and rate limit 429 after 10 requests/minute.
