# Day 12 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

1. `OPENAI_API_KEY` is hardcoded in `01-localhost-vs-production/develop/app.py`.
2. `DATABASE_URL` contains a hardcoded username and password.
3. Configuration such as `DEBUG` and `MAX_TOKENS` is stored directly in code instead of environment variables.
4. The app logs secrets with `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`.
5. There is no `/health` endpoint for platform liveness checks.
6. The server binds to `localhost`, so it is not reachable from outside the container or cloud runtime.
7. The port is fixed at `8000` instead of reading `PORT` from the environment.
8. `reload=True` is enabled, which is useful in development but unsafe for production.
9. There is no readiness endpoint to tell a load balancer when the app is ready for traffic.
10. There is no explicit graceful shutdown flow for cloud/container termination.

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Why Important? |
|---------|---------|------------|----------------|
| Config | Hardcoded constants | Environment variables in `config.py` | Allows different settings for local, staging, and production without code changes. |
| Secrets | API key and DB URL in source code | Secrets loaded from env | Prevents leaking credentials in GitHub or logs. |
| Host binding | `localhost` | `0.0.0.0` | Containers and cloud platforms need the app to accept external traffic. |
| Port | Fixed `8000` | `PORT` env var | Railway/Render inject dynamic ports. |
| Debug mode | `reload=True` | Controlled by `DEBUG` | Avoids dev reload behavior in production. |
| Health check | Missing | `GET /health` | Lets platforms restart unhealthy containers. |
| Readiness | Missing | `GET /ready` | Lets a load balancer route traffic only when startup is complete. |
| Logging | `print()` and secret logging | Structured JSON logs without secrets | Makes logs searchable and safer for observability. |
| Shutdown | No lifecycle handling | FastAPI lifespan and SIGTERM handler | Gives the service a chance to finish work and clean up before stopping. |
| Input validation | Minimal | Checks missing `question` | Returns predictable errors instead of unexpected failures. |

### Checkpoint 1

- Hardcoded secrets are dangerous because they can be committed, pushed, logged, copied into Docker images, and reused by attackers.
- Environment variables keep config outside code and support the 12-factor app style.
- Health checks let cloud platforms detect and restart broken processes.
- Graceful shutdown means the app stops accepting traffic and lets current requests finish before exit.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

1. Base image: `python:3.11`.
2. Working directory: `/app`.
3. `COPY requirements.txt` happens before application code to reuse Docker layer cache when dependencies do not change.
4. `CMD` provides the default command for the container and can be overridden at runtime. `ENTRYPOINT` defines the executable that always runs unless explicitly overridden.

### Exercise 2.3: Multi-stage build

- Stage 1, `builder`, installs build tools and Python dependencies into `/root/.local`.
- Stage 2, `runtime`, copies only installed packages and app code into a slim runtime image.
- The image is smaller and safer because compilers, apt caches, and build-only tools are not included in the final runtime layer.

### Exercise 2.3: Image size comparison

- Develop: 1.66 GB (`day12-agent:develop`).
- Production: 236 MB (`day12-agent:production`).
- Difference: production is about 85.8% smaller than develop.
- Final project image: 247 MB (`06-lab-complete-agent:latest`), under the 500 MB requirement.

### Exercise 2.4: Docker Compose stack

The production compose stack starts:

- `agent`: FastAPI application.
- `redis`: shared storage/cache for session, rate limiting, or other state.
- `nginx`: reverse proxy and load balancer in front of the agent service.

Communication flow:

`Client -> Nginx -> Agent -> Redis`

Nginx is the only public entrypoint. Agent instances stay internal and talk to Redis on the Docker network.

### Checkpoint 2

- Dockerfiles define the filesystem, dependencies, exposed ports, health checks, user, and startup command for an image.
- Multi-stage builds keep final runtime images smaller and cleaner.
- Docker Compose starts multiple services and connects them through named service DNS.
- `docker logs`, `docker exec`, `docker compose ps`, and health checks are the main debugging tools.

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- Status: deployment configuration is prepared in `03-cloud-deployment/railway/railway.toml` and `06-lab-complete/railway.toml`.
- Public URL: pending until Railway login/project creation is completed.
- Required environment variables:
  - `ENVIRONMENT=production`
  - `AGENT_API_KEY=<secret>`
  - `REDIS_URL=<managed redis url>`
  - `MONTHLY_BUDGET_USD=10.0`
  - `RATE_LIMIT_PER_MINUTE=10`

Test commands after deploy:

```bash
curl https://<railway-domain>/health
curl https://<railway-domain>/ready
curl -X POST https://<railway-domain>/ask \
  -H "X-API-Key: <secret>" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user1","question":"Hello"}'
```

### Exercise 3.2: Render vs Railway config

| Topic | Railway `railway.toml` | Render `render.yaml` |
|-------|-------------------------|----------------------|
| Build config | Uses `[build]` and `builder` | Uses `runtime`, `buildCommand`, or Docker runtime |
| Start command | `startCommand` under `[deploy]` | `startCommand` under service entry |
| Health check | `healthcheckPath` | `healthCheckPath` |
| Env vars | Set through CLI/dashboard | Declared in blueprint, with secrets using `sync: false` or generated values |
| Multi-service | Usually configured per service/project | Blueprint can define web service plus Redis in one file |
| Deployment trigger | `railway up` or Git integration | GitHub auto deploy through blueprint |

### Exercise 3.3: GCP Cloud Run

`cloudbuild.yaml` describes CI/CD:

1. Install requirements and run tests.
2. Build a Docker image.
3. Push the image to Google Container Registry.
4. Deploy the image to Cloud Run.

`service.yaml` describes the Cloud Run service:

- Public ingress.
- Min/max autoscaling.
- CPU and memory limits.
- `PORT=8000`.
- Secrets loaded from Secret Manager.
- Liveness probe on `/health`.
- Startup probe on `/ready`.

### Checkpoint 3

- At least one cloud platform config is ready.
- Public URL is still pending because it requires an authenticated Railway/Render account.
- Environment variables should be set in the cloud dashboard or CLI, not committed.
- Logs are viewed with Railway/Render dashboards or provider CLI commands.

## Part 4: API Security

### Exercise 4.1: API Key authentication

In `04-api-gateway/develop/app.py`, the API key is checked in `verify_api_key` through the `X-API-Key` header.

- Missing key returns `401`.
- Wrong key returns `403`.
- Correct key allows access to `POST /ask`.
- Key rotation is done by changing `AGENT_API_KEY` in the environment and restarting/redeploying the service. For zero-downtime rotation, support two valid keys temporarily.

### Exercise 4.2: JWT authentication

In `04-api-gateway/production`, the JWT flow is:

1. User calls `/auth/token` with username and password.
2. `authenticate_user` checks credentials.
3. `create_token` signs a JWT with username, role, and expiry.
4. Protected endpoints use `verify_token`.
5. The client sends `Authorization: Bearer <token>` on later requests.

### Exercise 4.3: Rate limiting

`04-api-gateway/production/rate_limiter.py` uses a sliding window algorithm backed by an in-memory deque per user.

- Normal user limit: 10 requests per 60 seconds.
- Admin limit: 100 requests per 60 seconds.
- Admin bypass is implemented as a higher limit through `rate_limiter_admin`.
- When exceeded, the API raises `429 Too Many Requests` with `Retry-After` and rate-limit headers.

### Exercise 4.4: Cost guard implementation

The cost guard in `04-api-gateway/production/cost_guard.py` tracks per-user monthly usage and a global monthly budget.

- It estimates cost from input and output token counts.
- Each user has a monthly budget.
- Redis is used when `REDIS_URL` is available.
- If Redis is unavailable, it falls back to memory for the local demo.
- It raises `402` when a user exceeds their monthly budget.
- It raises `503` when the global monthly budget is exhausted.

### Checkpoint 4

- API key authentication is implemented.
- JWT flow is implemented in the production security sample.
- Rate limiting is implemented with a sliding window.
- Cost guard is implemented with Redis support and memory fallback.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

`05-scaling-reliability/develop/app.py` implements:

- `GET /health`: liveness probe with status, uptime, version, environment, timestamp, and memory check if `psutil` is installed.
- `GET /ready`: readiness probe that returns `503` if the app is not ready and includes in-flight request count when ready.

### Exercise 5.2: Graceful shutdown

Graceful shutdown is handled through:

- FastAPI lifespan shutdown logic.
- `_is_ready = False` during shutdown.
- `_in_flight_requests` tracking.
- Waiting up to 30 seconds for active requests.
- SIGTERM/SIGINT handler for shutdown logging.

### Exercise 5.3: Stateless design

`05-scaling-reliability/production/app.py` stores sessions in Redis instead of process memory when Redis is available.

Why it matters:

- With multiple replicas, each process has separate memory.
- Redis gives all instances access to the same conversation/session state.
- If one instance dies, another instance can continue the same conversation.

### Exercise 5.4: Load balancing

The scaling production stack uses Nginx as the public entrypoint and routes traffic to the `agent` service inside Docker Compose.

When run with:

```bash
docker compose up --scale agent=3
```

Docker creates multiple `agent` containers and Nginx distributes traffic across healthy instances.

### Exercise 5.5: Test stateless

`05-scaling-reliability/production/test_stateless.py` validates that conversation state survives across instance changes because state is stored in Redis.

Expected result:

- Create conversation.
- Kill or replace one instance.
- Send another request.
- Conversation history still exists because Redis holds the session.

### Checkpoint 5

- Health and readiness endpoints are implemented.
- Graceful shutdown is implemented.
- Production sample uses Redis-backed stateless design.
- Nginx provides load balancing.
- Stateless test script is present.

## Part 6: Final Project

The completed project is in `06-lab-complete`.

### Functional requirements

- [x] Agent answers questions through `POST /ask`.
- [x] Conversation history is supported through Redis-backed history and `GET /history/{user_id}`.
- [ ] Streaming responses are optional and not implemented.

### Non-functional requirements

- [x] Multi-stage Dockerfile.
- [x] Config from environment variables.
- [x] API key authentication.
- [x] Rate limiting at 10 requests/minute per user.
- [x] Cost guard at $10/month per user.
- [x] Health check endpoint.
- [x] Readiness check endpoint.
- [x] Graceful shutdown handling.
- [x] Stateless design with Redis in Docker Compose and production mode.
- [x] Structured JSON logging.
- [x] Railway and Render deployment config.
- [ ] Public URL pending external cloud deployment.

### Local test commands

```bash
cd 06-lab-complete
docker compose up --scale agent=3

curl http://localhost/health
curl http://localhost/ready

curl -X POST http://localhost/ask \
  -H "X-API-Key: secret" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user1","question":"Explain Docker deployment"}'

curl -H "X-API-Key: secret" http://localhost/history/user1
```

### Production readiness notes

- `docker build -t day12-lab-complete:latest .` passed; final image size is 247 MB.
- `docker compose up -d --build --scale agent=3` passed after fixing the runtime `PYTHONPATH`.
- Compose status showed 3 healthy `agent` containers, 1 healthy `redis`, and `nginx` exposed on port 80.
- `docker compose config` was checked successfully.
- `python check_production_ready.py` passed 20/20 checks.
- FastAPI smoke test through Nginx passed: `/health` 200, `/ready` 200 with Redis connected, missing auth 401, authenticated `/ask` 200, and rate limit 429 on request 11.
