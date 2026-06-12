# Deployment Information

## Status

Ready for deployment, with local code checks passing. No public URL has been created from this local environment yet because Railway/Render CLI login is not available here.

The repository includes deployment config for both Railway and Render:

- Railway: `06-lab-complete/railway.toml`
- Render: `06-lab-complete/render.yaml`

## Public URL

Pending cloud deployment.

After deployment, replace this value:

```text
<PUBLIC_URL>
```

## Platform

Recommended: Render Blueprint or Railway Docker deployment.

## Local Test Commands

Run from `06-lab-complete`:

```bash
docker compose up --scale agent=3
```

### Health Check

```bash
curl http://localhost/health
```

Expected:

```json
{"status":"ok"}
```

### Readiness Check

```bash
curl http://localhost/ready
```

Expected:

```json
{"ready":true}
```

### Authentication Required

```bash
curl -X POST http://localhost/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello"}'
```

Expected: `401`.

### API Test With Authentication

```bash
curl -X POST http://localhost/ask \
  -H "X-API-Key: secret" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello"}'
```

Expected: `200` with an agent answer.

### History Test

```bash
curl -H "X-API-Key: secret" http://localhost/history/test
```

Expected: previous conversation messages for `test`.

### Rate Limiting Test

```bash
for i in {1..15}; do
  curl -X POST http://localhost/ask \
    -H "X-API-Key: secret" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"rate-test\",\"question\":\"test $i\"}"
  echo
done
```

Expected: requests eventually return `429` after 10 requests per minute.

## Local Verification Completed

- `python check_production_ready.py`: passed 20/20.
- `docker build -t day12-lab-complete:latest .`: passed.
- Final Docker image size: 247 MB (`day12-lab-complete:latest` and `06-lab-complete-agent:latest`).
- `docker compose up -d --build --scale agent=3`: passed.
- Compose status:
  - 3 healthy `agent` containers
  - 1 healthy `redis` container
  - 1 `nginx` container exposed on `localhost:80`
- FastAPI smoke test through Nginx:
  - `/health`: 200
  - `/ready`: 200 with Redis connected
  - `/ask` without `X-API-Key`: 401
  - `/ask` with `X-API-Key`: 200
  - rate limiting: 429 on request 11
- `docker compose config`: valid.

## Cloud Test Commands

After replacing `<PUBLIC_URL>` and `<API_KEY>`:

```bash
curl <PUBLIC_URL>/health
curl <PUBLIC_URL>/ready

curl -X POST <PUBLIC_URL>/ask \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello from production"}'
```

## Environment Variables Set

Required:

- `ENVIRONMENT=production`
- `PORT`
- `REDIS_URL`
- `AGENT_API_KEY`
- `RATE_LIMIT_PER_MINUTE=10`
- `RATE_LIMIT_WINDOW_SECONDS=60`
- `MONTHLY_BUDGET_USD=10.0`
- `REQUIRE_REDIS=true`
- `LOG_LEVEL` or `DEBUG=false`

Optional:

- `APP_NAME`
- `APP_VERSION`
- `OPENAI_API_KEY`
- `LLM_MODEL`
- `ALLOWED_ORIGINS`
- `SESSION_TTL_SECONDS`
- `MAX_HISTORY_MESSAGES`

## Railway Deployment Steps

```bash
cd 06-lab-complete
railway login
railway init
railway variables set ENVIRONMENT=production
railway variables set AGENT_API_KEY=<strong-secret>
railway variables set REDIS_URL=<managed-redis-url>
railway variables set RATE_LIMIT_PER_MINUTE=10
railway variables set MONTHLY_BUDGET_USD=10.0
railway variables set REQUIRE_REDIS=true
railway up
railway domain
```

## Render Deployment Steps

1. Push the repository to GitHub.
2. Open Render Dashboard.
3. Choose New -> Blueprint.
4. Connect the GitHub repository.
5. Select `06-lab-complete/render.yaml` if Render asks for the blueprint file.
6. Set `REDIS_URL` and confirm generated `AGENT_API_KEY`.
7. Deploy.
8. Copy the public service URL into this file.

## Screenshots

Screenshots should be added after local Docker or cloud deployment is running:

- `screenshots/dashboard.png`
- `screenshots/running.png`
- `screenshots/test.png`
