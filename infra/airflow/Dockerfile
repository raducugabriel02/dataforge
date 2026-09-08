# Imagine Airflow + dbt + modulul nostru de ingestie, ca sa poata rula in acelasi
# proces atat `dbt run/test` cat si parserele Python din ingestion/, fara subprocese
# separate care ar trebui sa-si gaseasca singure dependintele.
FROM apache/airflow:2.10.3-python3.12

# --chown=airflow:0: COPY creeaza fisierele ca root implicit, dar RUN-urile de mai jos
# (si containerul la runtime) ruleaza ca user-ul non-root `airflow` din imaginea de baza —
# fara chown, pip install -e nu ar putea scrie dataforge.egg-info in /opt/dataforge.
COPY --chown=airflow:0 pyproject.toml /opt/dataforge/pyproject.toml
COPY --chown=airflow:0 ingestion /opt/dataforge/ingestion
COPY --chown=airflow:0 scripts /opt/dataforge/scripts

# instalare editabila: codul e re-montat ca volum la runtime (vezi docker-compose.yml),
# deci modificarile locale se reflecta imediat, fara rebuild de imagine
RUN pip install --no-cache-dir -e "/opt/dataforge[dbt]"
