# Docker Deployment Quick Reference

This file provides **exact code snippets** for integrating the diarization pipeline into Docker deployments.

**Related Documentation**:
- [Speaker Labeling & Voice Embeddings](diarization_speaker_labeling.md) - Manual castaway labeling and embedding-based label propagation
- [Diarization Implementation Summary](diarization_implementation_summary.md) - Architecture overview

---

## 1. Development Deployment (`airflow/docker-compose.yaml`)

### Add Volume Mounts

Find the `x-airflow-common` section and add these lines to the `volumes:` list:

```yaml
x-airflow-common:
  &airflow-common
  # ... existing config ...
  volumes:
    # ... existing volumes ...
    - ../airflow/dags:/opt/airflow/dags
    - ../Database/sql:/opt/airflow/sql
    # ... other existing volumes ...

    # ADD THESE LINES FOR DIARIZATION:
    - /mnt/nas/Max2NUC Files:/mnt/nas/Max2NUC Files:ro  # NAS mount (read-only)
    - ../data_cache:/opt/airflow/data_cache              # Persistent output directory
```

### Add Environment Variables

Find the `environment: &airflow-common-env` section and add:

```yaml
environment: &airflow-common-env
  # ... existing variables ...
  AIRFLOW__CORE__EXECUTOR: CeleryExecutor
  # ... other existing vars ...

  # ADD THESE LINES FOR DIARIZATION:
  SURVIVOR_VIDEO_DIR: /mnt/nas/Max2NUC Files/TV Shows/Survivor (2000) {TvbId-76733}
  SURVIVOR_SUBTITLE_DIR: /mnt/nas/Max2NUC Files/Subtitles
  SURVIVOR_AUDIO_OUT_DIR: /opt/airflow/data_cache/survivor_audio
  SURVIVOR_DIARIZED_DIR: /opt/airflow/data_cache/survivor_diarized
  HF_TOKEN: ${HF_TOKEN}  # Will read from host .env file
  VERSION_COUNTRY: US
  USE_RAY: "false"
  RAY_ADDRESS: auto
  PYANNOTE_DIARIZATION_MODEL: pyannote/speaker-diarization-3.1
```

## 2. Production Deployment (`deploy/docker-compose.yml`)

### Add Volume Mounts

Find the `airflow-webserver` service and add to `volumes:`:

```yaml
airflow-webserver:
  # ... existing config ...
  volumes:
    - gamebot_dags:/opt/airflow/dags:ro
    - gamebot_logs:/opt/airflow/logs
    # ... other existing volumes ...

    # ADD THESE LINES FOR DIARIZATION:
    - /mnt/nas/Max2NUC Files:/mnt/nas/Max2NUC Files:ro
    - gamebot_data_cache:/opt/airflow/data_cache
```

Also add to `airflow-scheduler` and `airflow-worker` services.

### Add Named Volume

At the bottom of the file, add to `volumes:` section:

```yaml
volumes:
  warehouse_db_data:
  gamebot_dags:
  gamebot_logs:
  # ... other existing volumes ...

  # ADD THIS LINE:
  gamebot_data_cache:  # Persistent storage for diarization outputs
```

### Add Environment Variables

Find `environment: &airflow-common-env` and add the same variables as dev deployment above.

## 3. Dockerfile Updates (`airflow/Dockerfile`)

Add ffmpeg installation before the final USER statement:

```dockerfile
# ... existing Dockerfile content ...

# Install system dependencies for diarization
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Switch back to airflow user
USER airflow

# ... rest of Dockerfile ...
```

## 4. Python Dependencies (`airflow/requirements.txt`)

Add these lines to the file:

```txt
# ... existing requirements ...

# Diarization pipeline dependencies
pyannote.audio>=3.1.0
torch>=2.0.0
srt>=3.5.0

# Optional: Ray for distributed processing
# Uncomment if using Ray:
# ray[default]>=2.7.0
```

## 5. Host Environment File (`.env`)

Copy `.env.example` to `.env` and set these required variables:

```bash
# Required: Hugging Face token (get from https://huggingface.co/settings/tokens)
HF_TOKEN=hf_your_actual_token_here

# Optional: Adjust paths if your NAS mount is different
# SURVIVOR_VIDEO_DIR=/your/actual/path/to/videos
# SURVIVOR_SUBTITLE_DIR=/your/actual/path/to/subtitles
```

## 6. Rebuild Docker Images

After making the above changes:

### For Development:
```bash
cd airflow
docker compose down
docker compose build --no-cache
docker compose up -d
```

### For Production:
```bash
cd deploy
docker compose down
docker compose build --no-cache
docker compose up -d
```

## Complete Example: Development docker-compose.yaml Snippet

Here's a complete snippet showing the relevant sections with diarization additions:

```yaml
x-airflow-common:
  &airflow-common
  build:
    context: ..
    dockerfile: airflow/Dockerfile
  image: gamebot-airflow:latest
  env_file:
    - ../.env
  environment: &airflow-common-env
    AIRFLOW__CORE__EXECUTOR: CeleryExecutor
    AIRFLOW__CORE__LOAD_EXAMPLES: "False"
    AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "False"
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
    AIRFLOW__CELERY__RESULT_BACKEND: db+postgresql://airflow:airflow@postgres/airflow
    AIRFLOW__CELERY__BROKER_URL: redis://:@redis:6379/0
    REDIS_HOST: redis
    REDIS_PORT: "6379"
    DB_HOST: warehouse-db
    DB_PORT: "5432"
    REDIS_URL: redis://redis:6379/0
    DB_NAME: ${DB_NAME:-survivor_dw_dev}
    DB_USER: ${DB_USER:-survivor_dev}
    DB_PASSWORD: ${DB_PASSWORD:-survivor_dev_password}
    SURVIVOR_ENV: ${SURVIVOR_ENV:-dev}
    GAMEBOT_TARGET_LAYER: ${GAMEBOT_TARGET_LAYER:-gold}
    AIRFLOW_CONN_SURVIVOR_POSTGRES: postgresql+psycopg2://${DB_USER:-survivor_dev}:${DB_PASSWORD:-survivor_dev_password}@warehouse-db:5432/${DB_NAME:-survivor_dw_dev}
    AIRFLOW_UID: ${AIRFLOW_UID}

    # Diarization pipeline configuration
    SURVIVOR_VIDEO_DIR: /mnt/nas/Max2NUC Files/TV Shows/Survivor (2000) {TvbId-76733}
    SURVIVOR_SUBTITLE_DIR: /mnt/nas/Max2NUC Files/Subtitles
    SURVIVOR_AUDIO_OUT_DIR: /opt/airflow/data_cache/survivor_audio
    SURVIVOR_DIARIZED_DIR: /opt/airflow/data_cache/survivor_diarized
    HF_TOKEN: ${HF_TOKEN}
    VERSION_COUNTRY: US
    USE_RAY: "false"
    RAY_ADDRESS: auto
    PYANNOTE_DIARIZATION_MODEL: pyannote/speaker-diarization-3.1

  volumes:
    - ../airflow/dags:/opt/airflow/dags
    - ../Database/sql:/opt/airflow/sql
    - ../Database:/opt/airflow/Database
    - ../dbt:/opt/airflow/dbt
    - ../gamebot_core:/opt/airflow/gamebot_core
    - ../gamebot_lite:/opt/airflow/gamebot_lite
    - ../scripts:/opt/airflow/scripts
    - ../params.py:/opt/airflow/params.py
    - ../.git:/opt/airflow/.git:ro
    - ../run_logs:/opt/airflow/run_logs
    - airflow-logs:/opt/airflow/logs
    - airflow-plugins:/opt/airflow/plugins

    # Diarization pipeline volume mounts
    - /mnt/nas/Max2NUC Files:/mnt/nas/Max2NUC Files:ro
    - ../data_cache:/opt/airflow/data_cache

  user: "${AIRFLOW_UID:-1000}:0"
  depends_on:
    redis:
      condition: service_healthy
    postgres:
      condition: service_healthy
    warehouse-db:
      condition: service_healthy
  networks:
    - gamebot
```

## Verification Checklist

After making changes, verify:

- [ ] Docker images rebuild successfully (`docker compose build`)
- [ ] Containers start without errors (`docker compose up -d`)
- [ ] NAS mounts are accessible inside containers:
  ```bash
  docker compose exec airflow-worker ls -la "/mnt/nas/Max2NUC Files/TV Shows/Survivor (2000) {TvbId-76733}/"
  ```
- [ ] ffmpeg is installed:
  ```bash
  docker compose exec airflow-worker ffmpeg -version
  ```
- [ ] Python packages are installed:
  ```bash
  docker compose exec airflow-worker python -c "import pyannote.audio; print('OK')"
  ```
- [ ] Environment variables are set:
  ```bash
  docker compose exec airflow-worker env | grep SURVIVOR_
  ```
- [ ] DAG appears in Airflow UI without errors
- [ ] Output directories are writable:
  ```bash
  docker compose exec airflow-worker touch /opt/airflow/data_cache/test.txt
  ```

## Troubleshooting Docker Setup

### Issue: NAS mount not accessible

**Symptom:** `FileNotFoundError: SURVIVOR_VIDEO_DIR does not exist`

**Fix:**
1. Verify NAS is mounted on host: `ls -la /mnt/nas/`
2. Check volume mount syntax in docker-compose.yaml
3. Restart containers: `docker compose restart`

### Issue: ffmpeg not found

**Symptom:** `ffmpeg not found in PATH`

**Fix:**
1. Verify Dockerfile changes were applied
2. Rebuild image: `docker compose build --no-cache airflow-webserver`
3. Restart: `docker compose up -d`

### Issue: Permission denied writing to data_cache

**Symptom:** `PermissionError: [Errno 13] Permission denied: '/opt/airflow/data_cache/...'`

**Fix:**
1. Create directory on host: `mkdir -p data_cache`
2. Set permissions: `chmod 777 data_cache` (or match AIRFLOW_UID)
3. Restart: `docker compose restart`

### Issue: pyannote.audio not found

**Symptom:** `ModuleNotFoundError: No module named 'pyannote'`

**Fix:**
1. Add to airflow/requirements.txt
2. Rebuild: `docker compose build --no-cache`
3. Restart: `docker compose up -d`

## Ray Cluster Setup (Advanced)

For multi-machine Ray deployment:

### 1. Start Ray on Dedicated Machines (Outside Docker)

**Head Node:**
```bash
ray start --head --port=6379 --dashboard-host=0.0.0.0
```

**Worker Nodes:**
```bash
ray start --address=<head-node-ip>:6379
```

### 2. Update docker-compose.yaml

```yaml
environment: &airflow-common-env
  # ... other vars ...
  USE_RAY: "true"
  RAY_ADDRESS: ray://<head-node-ip>:10001  # Ray Client address
```

### 3. Network Configuration

Ensure Airflow containers can reach Ray nodes:
- Open firewall ports: 6379, 8265, 10001
- Use bridge network or host network mode
- Verify connectivity: `telnet <head-node-ip> 6379`

## Minimal Working Example

For a quick test without NAS:

1. Create local test directories:
```bash
mkdir -p test_videos test_subtitles data_cache
```

2. Update docker-compose.yaml:
```yaml
SURVIVOR_VIDEO_DIR: /opt/airflow/test_videos
SURVIVOR_SUBTITLE_DIR: /opt/airflow/test_subtitles

volumes:
  - ../test_videos:/opt/airflow/test_videos
  - ../test_subtitles:/opt/airflow/test_subtitles
```

3. Place test files and run DAG manually

This lets you test the pipeline without requiring the full NAS setup.
