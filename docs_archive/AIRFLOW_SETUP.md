# Airflow Telepítési és Indítási Útmutató

## 🚀 Gyors Start

### 1. Környezeti változók ellenőrzése (.env)
```bash
# .env fájl (ha még nincs, hozd létre)
POSTGRES_USER=airflow
POSTGRES_PASSWORD=airflow
POSTGRES_DB=airflow
AIRFLOW_USERNAME=admin
AIRFLOW_PASSWORD=admin
```

### 2. Docker services build és indítás
```bash
# Build (első alkalommal vagy Dockerfile változás után)
docker-compose build

# Airflow inicializálás (első indítás előtt egyszer)
docker-compose run --rm airflow-webserver bash /opt/airflow/airflow-init.sh

# Összes service indítása
docker-compose up -d

# Logok követése
docker-compose logs -f
```

### 3. Services ellenőrzése
```bash
# Futó containerek listája
docker-compose ps

# Várható output:
# - postgres (Airflow metadata DB)
# - redis (Cache + Celery broker)
# - ollama (LLM server)
# - airflow-webserver (Orchestration UI - port 8080)
# - airflow-scheduler (DAG executor)
# - airflow-worker (2x replika - parallel task execution)
# - app (Flask webapp - port 5001)
```

### 4. Web felületek elérése
- **Airflow UI**: http://localhost:8080
  - Username: `admin`
  - Password: `admin`
- **Flask App**: http://localhost:5001
  - Admin jelszó: `SzuperTitkosJelszo2025!`

## 📊 Airflow használata

### DAG manuális triggerelés (Airflow UI-ból)
1. Nyisd meg: http://localhost:8080
2. Keresd meg a `ingatlan_llm_pipeline` DAG-ot
3. Kapcsold BE a DAG-ot (toggle gomb)
4. Klikkelj a "Trigger DAG" gombra (play ikon)
5. Opcionális: Add meg a conf paramétert: `{"test_mode": true}` teszt módhoz

### DAG manuális triggerelés (Flask webapp-ból)
1. Lépj be az admin felületre: http://localhost:5001/login
2. Klikkelj az "LLM Adatfeldolgozás Indítása" gombra (teljes futtatás)
3. VAGY klikkelj a "🧪 TESZT Futtatás" gombra (gyors validáció)
4. A webapp átirányít az Airflow UI-ra a haladás követéséhez

### DAG állapot követése
- **Airflow UI**: http://localhost:8080/dags/ingatlan_llm_pipeline/grid
  - Task-onkénti haladás (zöld = success, piros = failed, sárga = running)
  - Logok megtekintése (klikkelj egy task-ra → "Log" gomb)
  - Grafikus DAG vizualizáció ("Graph" tab)

### DAG automatikus ütemezés
- Alapértelmezett: **naponta egyszer** (`schedule_interval='@daily'`)
- Kikapcsolás: Airflow UI → DAG toggle OFF
- Módosítás: `dags/ingatlan_pipeline_dag.py` → `schedule_interval` paraméter

## 🔧 Hibaelhárítás

### "Airflow webserver nem indul"
```bash
# Inicializálás újrafuttatása
docker-compose run --rm airflow-webserver bash /opt/airflow/airflow-init.sh

# Adatbázis reset (VIGYÁZAT: törli az összes DAG run history-t!)
docker-compose down -v
docker volume rm thesis_project_postgres_data
docker-compose up -d
```

### "DAG nem látható az Airflow UI-ban"
```bash
# Scheduler logok ellenőrzése
docker-compose logs airflow-scheduler

# DAG szintaxis ellenőrzése
docker-compose exec airflow-webserver python /opt/airflow/dags/ingatlan_pipeline_dag.py

# DAG refresh
docker-compose restart airflow-scheduler
```

### "Celery worker nem dolgozik"
```bash
# Worker logok
docker-compose logs airflow-worker

# Worker újraindítás
docker-compose restart airflow-worker
```

## 📦 Adatok és eredmények

### Output fájlok (Docker volume-ban megmaradnak)
- **Releváns hirdetések**: `/workspace/parquet/core_layer_filtered.parquet`
- **Irreleváns hirdetések**: `/workspace/parquet/core_layer_irrelevant.parquet`
- **LLM döntések log**: `/workspace/llm_decisions_log.csv`
- **ML modell**: `/workspace/price_prediction_model.pkl`

### Hozzáférés a fájlokhoz
```bash
# Docker volume-ból másolás
docker cp thesis_project-app-1:/workspace/parquet/core_layer_filtered.parquet ./

# Vagy direkt elérés (volume mount miatt)
ls parquet/
```

## 🧹 Leállítás és tisztítás

```bash
# Graceful shutdown
docker-compose down

# Volumes megtartásával (adatok megmaradnak)
docker-compose down

# Volumes törlésével (ÖSSZES adat törlése!)
docker-compose down -v

# Csak Airflow adatok törlése
docker volume rm thesis_project_postgres_data thesis_project_airflow_logs
```

## 🔑 Fontos környezeti változók

| Változó | Alapértelmezett | Leírás |
|---------|----------------|--------|
| `AIRFLOW__CORE__EXECUTOR` | `CeleryExecutor` | Task executor típus |
| `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION` | `false` | DAG-ok alapból aktívak |
| `AIRFLOW__CORE__LOAD_EXAMPLES` | `false` | Példa DAG-ok betöltése |
| `OLLAMA_HOST` | `http://ollama:11434` | LLM server URL |
| `REDIS_HOST` | `redis` | Cache + Celery broker host |
| `ADMIN_PASSWORD` | `SzuperTitkosJelszo2025!` | Flask admin jelszó |

## 📚 További dokumentáció

- **Airflow**: https://airflow.apache.org/docs/
- **Celery Executor**: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/executor/celery.html
- **DAG írás**: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html
