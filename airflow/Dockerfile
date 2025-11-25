FROM apache/airflow:2.9.1

USER root

# Install system dependencies (including ffmpeg for diarization pipeline)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=airflow:0 airflow/requirements.txt /tmp/airflow-requirements.txt

USER airflow

RUN pip install --no-cache-dir -r /tmp/airflow-requirements.txt && rm /tmp/airflow-requirements.txt

# Copy the application code
COPY --chown=airflow:0 airflow/dags /opt/airflow/dags
COPY --chown=airflow:0 scripts /opt/airflow/scripts
COPY --chown=airflow:0 gamebot_core /opt/airflow/gamebot_core
COPY --chown=airflow:0 dbt /opt/airflow/dbt
COPY --chown=airflow:0 Database /opt/airflow/Database
COPY --chown=airflow:0 params.py /opt/airflow/params.py

# Copy entrypoint wrapper for production branch protection
USER root
COPY --chown=airflow:0 airflow/entrypoint-wrapper.sh /entrypoint-wrapper.sh
RUN chmod +x /entrypoint-wrapper.sh

USER airflow
ENTRYPOINT ["/entrypoint-wrapper.sh"]
CMD ["airflow"]
