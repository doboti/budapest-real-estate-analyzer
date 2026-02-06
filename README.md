# Budapest Ingatlan Elemző Platform

> LLM-alapú ingatlanhirdetés feldolgozás, szűrés és árpredikció - Szakdolgozat projekt

## 📋 Tartalomjegyzék

- [Projekt Áttekintés](#projekt-áttekintés)
- [Főbb Funkciók](#főbb-funkciók)
- [Technológiai Stack](#technológiai-stack)
- [Telepítés és Indítás](#telepítés-és-indítás)
- [Használat](#használat)
- [Architektúra](#architektúra)
- [Admin Funkciók](#admin-funkciók)
- [API Endpoints](#api-endpoints)
- [Fejlesztés és Tesztelés](#fejlesztés-és-tesztelés)

---

## 🎯 Projekt Áttekintés

Ez a platform Budapest ingatlanhirdetéseit dolgozza fel nagy nyelvi modell (LLM) segítségével. A rendszer képes:

- **Automatikus szűrésre**: Releváns/irreleváns hirdetések elválasztása
- **Adatkinyerésre**: Szöveges leírásokból strukturált adatok (alapterület, szobaszám, stb.)
- **Árpredikció**: Machine Learning alapú árbecsülés
- **Térbeli analízis**: Budapest kerületek szerint csoportosított adatok
- **Interaktív vizualizáció**: Térképes megjelenítés, ártrendek, statisztikák

**Használati eset:** Nagyobb ingatlanközvetítő cégek, piackutatók, befektetők számára hasznos eszköz a budapesti lakáspiac gyors áttekintésére és elemzésére.

---

## ✨ Főbb Funkciók

### 🤖 LLM-alapú Feldolgozás

- **Ollama** lokális LLM inference (llama3.2:3b, mistral:7b modellek)
- **Redis cache**: LLM válaszok gyorsítótárazása (költségcsökkentés + sebesség)
- **Inkrementális feldolgozás**: Csak új hirdetések elemzése
- **Parallel processing**: Airflow + Celery workers párhuzamos végrehajtás

### 📊 Adatkezelés és Megjelenítés

- **27,000+ hirdetés** (core_data.parquet - GCP Cloud Storage-ból letölthető)
- **DuckDB SQL lekérdezések**: Gyors adatelemzés parquet fájlokon
- **Interaktív térképek**: Leaflet.js + GeoJSON Budapest kerülethatárok
- **Szűrhető adattáblák**: Bootstrap DataTables + backend pagináció

### 🎯 ML Árpredikció

- **RandomForestRegressor** modell
- **Jellemzők**: kerület, alapterület, szobaszám, ár/m², építési év, emelet
- **Metrikák**: R², MAE, MAPE
- **Model persistencia**: Pickle (.pkl) fájl tárolás

### ☁️ Cloud Integráció

- **GCP Storage**: Automatikus parquet file szinkronizáció
- **Version checking**: Lokális vs. cloud fájl összehasonlítás
- **One-click download**: Admin dashboardról frissítés

---

## 🛠️ Technológiai Stack

### Backend
- **Flask 3.0** - Web framework
- **Apache Airflow 2.10** - Workflow orchestration
- **Redis 7.4** - Cache + Celery broker
- **Ollama** - LLM inference server
- **DuckDB** - Parquet SQL queries
- **Pandas + PyArrow** - Adatfeldolgozás

### Frontend
- **Bootstrap 5** - UI komponensek
- **Leaflet.js** - Térképes megjelenítés
- **Chart.js** - Grafikonok (ártrendek)
- **Jinja2** - Template engine

### Infrastructure
- **Docker + Docker Compose** - Konténerizáció
- **PostgreSQL** - Airflow metadata DB
- **NVIDIA GPU** - LLM inference gyorsítás (opcionális)

---

## 🚀 Telepítés és Indítás

### Előfeltételek

```bash
# Szükséges szoftverek:
- Docker Desktop (Windows/Mac) vagy Docker Engine (Linux)
- Git
- NVIDIA GPU + NVIDIA Container Toolkit (opcionális, LLM gyorsításhoz)
```

### 1. Repository klónozása

```bash
git clone <repository-url>
cd thesis_project
```

### 2. GCP Credentials beállítása

**Service Account JSON kulcs** szükséges a GCP Storage eléréséhez:

1. Hozz létre service accountot a [GCP Console](https://console.cloud.google.com/iam-admin/serviceaccounts)-ban
2. Role: **Storage Object Viewer**
3. Töltsd le a JSON kulcsot
4. Másold a projekt gyökérbe `gcp-credentials.json` néven

```bash
# Példa:
cp ~/Downloads/thesis-work-474807-d60c5ba9a8d4.json ./gcp-credentials.json
```

### 3. Environment fájl (opcionális)

Hozz létre `.env` fájlt saját jelszavakkal:

```env
ADMIN_PASSWORD=SzuperTitkosJelszo2025!
SECRET_KEY=your_very_long_random_secret_key_here
AIRFLOW__WEBSERVER__SECRET_KEY=another_long_secret_key
```

### 4. Docker konténerek indítása

```bash
# Első indítás - Airflow adatbázis inicializálás
docker-compose up airflow-init

# Ollama modellek letöltése (egyszer kell futtatni)
docker-compose up -d ollama
docker exec -it thesis_project-ollama-1 ollama pull llama3.2:3b
docker exec -it thesis_project-ollama-1 ollama pull mistral:7b

# Teljes stack indítása
docker-compose up -d

# Logok követése
docker-compose logs -f app
```

### 5. Alkalmazás elérése

| Szolgáltatás | URL | Leírás |
|--------------|-----|--------|
| **Flask App** | http://localhost:5001 | Főalkalmazás |
| **Airflow Web UI** | http://localhost:8081 | DAG monitorozás |
| **Ollama API** | http://localhost:11434 | LLM szerver |

**Admin bejelentkezés**: `admin` / `SzuperTitkosJelszo2025!`

---

## 📖 Használat

### Első Lépések

1. **Bejelentkezés**: http://localhost:5001/login
2. **Admin Dashboard**: http://localhost:5001/admin
3. **GCP Adatletöltés**:
   - Kattints: "🔍 Frissítés Ellenőrzése"
   - Ha újabb verzió van: "⬇️ Letöltés GCP-ből"
4. **Modulok Tesztelése**: "🚀 Összes Modul Tesztelése" gomb
5. **LLM Feldolgozás**: "🚀 Adatfeldolgozás Indítása"

### Főbb Oldalak

#### 📊 Adattábla (`/data`)
- Szűrés kerület, ár, alapterület szerint
- Hivatkozások az eredeti hirdetésekhez
- Export funkcionalitás

#### 🗺️ Interaktív Térkép (`/map-interactive`)
- Budapesti kerületek GeoJSON ábrázolása
- Hover tooltip: kerület név + aktív hirdetések száma
- Dinamikus színezés hirdetésszám alapján

#### 📈 Ártrendek (`/price-trends`)
- Kerületenkénti átlagárak
- Heatmap vizualizáció
- Időbeli változások nyomon követése

#### 🔮 Árkalkulátor (`/prediction`)
- ML modell alapú árbecsülés
- Input: kerület, m², szobaszám, emelet, építési év
- Output: becsült ár (millió Ft) + megbízhatósági intervallum

#### 📈 Statisztikák (`/stats`)
- Feldolgozott/releváns/irreleváns hirdetések száma
- Cache találati arány
- Kerületenkénti megoszlások

---

## 🏗️ Architektúra

### Komponens Diagram

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Browser   │─────▶│  Flask App   │─────▶│   Ollama    │
│             │◀─────│  (port 5001) │◀─────│  LLM Server │
└─────────────┘      └──────┬───────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │    Redis     │
                     │  (Cache +    │
                     │   Broker)    │
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐      ┌─────────────┐
                     │   Airflow    │─────▶│  PostgreSQL │
                     │  Scheduler   │◀─────│  (Metadata) │
                     └──────┬───────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │Celery Workers│
                     │ (2x parallel)│
                     └──────────────┘
```

### Fájlstruktúra

```
thesis_project/
├── app/                          # Flask alkalmazás
│   ├── webapp.py                 # Fő backend (1200+ sor)
│   ├── *.html                    # Jinja2 templates
│   ├── airflow_api.py            # Airflow REST API kliens
│   ├── llm_cache.py              # Redis cache wrapper
│   ├── incremental_processing.py # Delta feldolgozás logika
│   ├── ml_worker_filter.py       # ML modell wrapper
│   └── static/                   # GeoJSON, CSS, JS
├── dags/                         # Airflow DAG-ok
│   └── ingatlan_pipeline_dag.py  # LLM feldolgozási workflow
├── parquet/                      # Adatfájlok
│   ├── core_data.parquet         # Nyers adatok (GCP-ből)
│   ├── core_layer_filtered.parquet # Releváns hirdetések
│   ├── core_layer_irrelevant.parquet # Irreleváns hirdetések
│   └── price_model.pkl           # Tanított ML modell
├── tests/                        # Unit tesztek
├── docker-compose.yml            # Multi-container orchestration
├── Dockerfile                    # Flask app image
├── Dockerfile.airflow            # Airflow image
├── requirements.txt              # Python dependencies
└── README.md                     # Ez a dokumentáció
```

### Adatfolyam

1. **Betöltés**: `core_data.parquet` → GCP Storage-ból → lokális parquet/
2. **Feldolgozás**: Airflow DAG → Celery workers → Ollama LLM → Redis cache
3. **Szűrés**: LLM döntés alapján → `core_layer_filtered.parquet` / `core_layer_irrelevant.parquet`
4. **Modell tanítás**: Filtered data → RandomForestRegressor → `price_model.pkl`
5. **Megjelenítés**: Flask routes → Jinja2 templates → Browser

---

## 🛠️ Admin Funkciók

### GCP Adatfrissítés

- **Ellenőrzés**: Összehasonlítja a lokális és GCP fájl timestamp-jét
- **Letöltés**: Automatikus backup + validálás parquet integritásra
- **Rollback**: Hiba esetén visszaállítja az előző verziót

### Modulok Tesztelése

Az "🔧 Modulok Tesztelése" szekció 6 komponenst ellenőriz:

| Modul | Teszt | Sikeres kimenet |
|-------|-------|-----------------|
| 🗄️ Redis | `redis_client.ping()` | Redis 7.4.7 - Kapcsolat OK |
| 🤖 Ollama | `/api/tags` endpoint | 2 modell elérhető: llama3.2:3b, mistral:7b |
| 📊 Parquet | File existence + read | 27,943 sor, 22 oszlop (18.1 MB) |
| ☁️ GCP | Storage bucket access | Bucket elérhető - Fájl: 18.1 MB |
| 🌪️ Airflow | `/health` endpoint | Airflow healthy - OK |
| 🎯 Model | pickle.load() | Modell betöltve - R²: 0.834, MAPE: 12.3% |

### LLM Adatfeldolgozás

**Teljes futtatás** (6-8 óra, ~27,000 hirdetés):
```python
POST /run-pipeline
```

**Workflow**:
1. Core data beolvasása
2. Inkrementális szűrés (csak új hirdetések)
3. LLM inference (Ollama)
4. Strukturált adatkinyerés (JSON parsing)
5. Relevant/irrelevant szétválasztás
6. Eredmények mentése

### Cache Kezelés

- **Törlés**: `POST /admin/cache/clear` → Redis FLUSHDB
- **Statisztikák**: `GET /cache-admin` → Hits/misses, hit rate, kulcsok száma

---

## 🔌 API Endpoints

### Publikus Endpoints

| Method | Path | Leírás |
|--------|------|--------|
| GET | `/` | Főoldal (dashboard) |
| GET | `/data` | Adattábla |
| GET | `/map-interactive` | Interaktív térkép |
| GET | `/price-trends` | Ártrendek |
| GET | `/prediction` | Árkalkulátor form |
| POST | `/predict` | ML predikció végrehajtása |
| GET | `/stats` | Statisztikák |
| GET | `/api/districts-summary` | Kerületek GeoJSON + hirdetésszám |

### Admin Endpoints (bejelentkezés szükséges)

| Method | Path | Leírás |
|--------|------|--------|
| POST | `/run-pipeline` | LLM feldolgozás indítása |
| POST | `/train-model` | ML modell tanítása |
| GET | `/admin/gcp/check-update` | GCP file verzió ellenőrzés |
| POST | `/admin/gcp/download` | GCP file letöltés |
| GET | `/admin/test-module/<module>` | Egyedi modul teszt |
| POST | `/admin/cache/clear` | Cache törlése |

---

## 🧪 Fejlesztés és Tesztelés

### Unit Tesztek Futtatása

```bash
# Docker konténeren belül
docker exec -it thesis_project-app-1 pytest tests/ -v

# Lokális környezetben (virtualenv)
python -m pytest tests/ -v --cov=app
```

**Teszt lefedettség**:
- `test_llm_cache.py` - Redis cache wrapper
- `test_incremental_processing.py` - Delta logika
- `test_task_manager.py` - Airflow task kezelés
- `test_models.py` - Adatmodellek

### Development Mode

A Flask app automatikus újratöltéssel fut (debug=True):

```python
# webapp.py
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
```

Kód módosítás után a konténer automatikusan újraindul.

### Logok

```bash
# Flask app logok
docker-compose logs -f app

# Airflow scheduler logok
docker-compose logs -f airflow-scheduler

# Összes szolgáltatás
docker-compose logs -f
```

---

## 🔧 Konfigurációs Lehetőségek

### Environment Variables

| Változó | Alapértelmezett | Leírás |
|---------|----------------|--------|
| `ADMIN_PASSWORD` | `SzuperTitkosJelszo2025!` | Admin bejelentkezési jelszó |
| `SECRET_KEY` | `supersecretkey` | Flask session kulcs |
| `OLLAMA_HOST` | `http://ollama:11434` | LLM szerver cím |
| `REDIS_HOST` | `redis` | Redis szerver host |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/workspace/gcp-credentials.json` | GCP service account kulcs |

### Airflow Beállítások

```yaml
# docker-compose.yml
environment:
  - AIRFLOW__CORE__EXECUTOR=CeleryExecutor
  - AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=false
  - AIRFLOW__CORE__LOAD_EXAMPLES=false
```

---

## 📝 Troubleshooting

### Gyakori Problémák

**1. Socket.IO 404 hibák**
```
Megoldás: Töröld a böngésző cache-t (Ctrl+Shift+Delete)
vagy használj Inkognitó módot.
```

**2. GCP "credentials not found" hiba**
```bash
# Ellenőrizd a fájl létezését
ls -la gcp-credentials.json

# Ellenőrizd a Docker mount-ot
docker exec thesis_project-app-1 ls -la /workspace/gcp-credentials.json

# Környezeti változó ellenőrzése
docker exec thesis_project-app-1 printenv GOOGLE_APPLICATION_CREDENTIALS
```

**3. Ollama modellek nem töltődnek be**
```bash
# Modellek manuális letöltése
docker exec -it thesis_project-ollama-1 ollama pull llama3.2:3b

# Elérhető modellek listázása
docker exec -it thesis_project-ollama-1 ollama list
```

**4. Airflow DAG nem jelenik meg**
```bash
# Scheduler újraindítása
docker-compose restart airflow-scheduler

# DAG validálás
docker exec -it thesis_project-airflow-scheduler-1 airflow dags list
```

---

## 👨‍💻 Fejlesztő Információk

**Projekt típus**: Szakdolgozat  
**Témavezető**: [Név]  
**Fejlesztő**: [Név]  
**Készült**: 2025-2026  
**Egyetem**: [Egyetem neve]

### Technológiai Választások Indoklása

- **Ollama**: Lokális LLM futtatás, költséghatékony (vs. OpenAI API)
- **Airflow**: Komplex workflow management, újraindítható taskek
- **Redis**: In-memory cache, gyors LLM válasz visszakeresés
- **DuckDB**: Parquet fájlok közvetlen SQL lekérdezése (in-process OLAP)
- **Flask**: Egyszerű, Python-native web framework

---

## 📄 License

Ez a projekt oktatási célokra készült szakdolgozat keretében.

---

## 🙏 Köszönetnyilvánítás

- **OpenStreetMap**: Budapest kerülethatárok adatai
- **Ollama projekt**: Nyílt forráskódú LLM inference
- **Apache Airflow közösség**: Workflow orchestration

---

**Utolsó frissítés**: 2026. február 4.
