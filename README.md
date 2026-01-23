# Budapest Ingatlan Ártrend Elemző és Predikciós Rendszer

## Projekt Áttekintés

Ez a komplex ingatlan elemző alkalmazás Budapest ingatlanpiacának elemzésére és előrejelzésére szolgál. A rendszer gépi tanulás és nagy nyelvi modellek (LLM) kombinációjával automatikusan szűri, kategorizálja és elemzi az ingatlanár-trendeket.

## Főbb Funkciók

### 🤖 **Intelligens Hirdetésszűrés**
- LLM-alapú relevanciaszűrés (Llama-3.2-3B-Instruct)
- Automatikus struktúrált adatkinyerés
- Szabályalapú előszűrés gyors feldolgozásért- **💾 Intelligens Cache Rendszer** - SHA256 hash alapú eredménytárolás
### 📊 **Ártrend Elemzés**
- Történeti áralakulás vizualizáció
- 6 hónapos árprognózis lineáris regresszióval
- Kerület és területméret szerinti szűrés
- Interaktív Chart.js grafikonok

### 🗺️ **Térképes Megjelenítés**
- Folium-alapú interaktív Budapest térkép
- Kerületek szerinti színkódolás
- GeoJSON határadatok

### 🎯 **ML Árpredikció**
- XGBoost és Random Forest modellek
- Automatikus modell kiválasztás
- Feature importance elemzés
- Teljesítménymetrikák

### 🔍 **Adatlekérdezés**
- SQL felület DuckDB-vel
- Természetes nyelvi lekérdezés LLM-mel
- Strukturált eredménymegjelenítés

## Technológiai Stack

### Backend
- **Python 3.9+** - Fő programozási nyelv
- **Flask** - Web framework
- **Pandas** - Adatmanipuláció
- **DuckDB** - Gyors analitikai lekérdezések
- **Ollama** - Helyi LLM szerverhez
- **Pydantic** - Adatvalidáció és séma kezelés
- **RQ** - Háttérfeladat-kezelés
- **Redis** - Cache és message broker
- **aiohttp** - Aszinkron HTTP kérések
- **asyncio** - Aszinkron I/O műveletek

### Machine Learning
- **Scikit-learn** - Általános ML algoritmusok
- **XGBoost** - Gradiens boosting modell
- **NumPy** - Numerikus számítások

### Vizualizáció
- **Folium** - Interaktív térképek
- **Chart.js** - Kliens oldali grafikonok
- **Bootstrap 5** - Responsive UI

### Infrastruktúra
- **Docker & Docker Compose** - Konténerizálás
- **NVIDIA GPU** támogatás
- **Parquet** - Hatékony adattárolás

## Rendszerkövetelmények

### Szoftver
- Docker 20.10+
- Docker Compose 2.0+
- Min. 8GB RAM
- 20GB szabad tárhely

### Ajánlott
- NVIDIA GPU CUDA támogatással
- 16GB+ RAM
- SSD tárhely

## Telepítés és Indítás

1. **Projekt letöltése**
   ```bash
   git clone <repository-url>
   cd thesis_project
   ```

2. **Adatfájl elhelyezése**
   ```bash
   # Helyezd el a core_data.parquet fájlt a projekt gyökerébe
   cp /path/to/core_data.parquet ./
   ```

3. **Alkalmazás indítása**
   ```bash
   docker-compose up --build
   ```

4. **Elérés**
   - Web alkalmazás: http://localhost:5001
   - Ollama API: http://localhost:11434

## Használati Útmutató

### 1. Adatfeldolgozás Indítása
- Nyisd meg a web alkalmazást
- Kattints az "Adatfeldolgozás indítása" gombra
- Az LLM automatikusan elemzi a hirdetéseket háttérben
- **Figyelem**: Nagy adathalmazok esetén ez több percig is eltarthat
- A folyamat állapota real-time követhető a webes felületen

### 2. Ártrend Elemzés
- Válaszd ki az elemzendő kerületet
- Állítsd be a területméret szűrőket
- Az elemzés 6 hónapos prognózist ad

### 3. Cache Admin
- **URL**: http://localhost:5001/admin/cache
- Real-time cache statisztikák megtekintése
- Cache törlés karbantartási célból
- Hit rate és memória használat monitorozása

### 4. ML Predikció
- Válassz egy ingatlan típust
- Add meg a paramétereket (terület, szobák, stb.)
- Kapj árpredikciót és konfidencia-intervallumot

### 4. Térkép Böngészés
- Interaktív térkép Budapest kerületeivel
- Kattints a kerületekre részletes statisztikákért

### 6. Adatlekérdezés
- SQL lekérdezések futtatása
- Természetes nyelvi kérdések feltevése
- Eredmények exportálása

## Projekt Struktúra

```
thesis_project/
├── app/
│   ├── main.py              # Fő adatfeldolgozó logika
│   ├── webapp.py            # Flask web alkalmazás
│   ├── price_trends.py      # Ártrend elemzés
│   ├── train_model.py       # ML modell tréning
│   ├── districts_features.py # Kerület adatok
│   ├── templates/           # HTML sablonok
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── price_trends.html
│   │   ├── prediction.html
│   │   ├── map.html
│   │   └── query_interface.html
│   └── static/              # Statikus fájlok
│       ├── budapest_districts.geojson
│       └── map_render.html
├── scripts/
│   └── osm_boundary_to_geojson.py  # Térkép előkészítés
├── parquet/                 # Adatfájlok könyvtára
├── dags/                    # Airflow DAG-ek (jövőbeli)
├── docker-compose.yml       # Docker szolgáltatások
├── Dockerfile              # Alkalmazás image
├── requirements.txt         # Python függőségek
└── README.md               # Ez a dokumentáció
```

## Adatfeldolgozási Pipeline

### 1. Adatbetöltés
- Parquet fájl beolvasása Pandas-sal
- Duplikáció kezelés article_id alapján
- Adattisztítás és validáció

### 2. LLM Elemzés
- **Cache ellenőrzés**: SHA256 hash alapú cache lookup
- **Aszinkron feldolgozás**: aiohttp + asyncio párhuzamos LLM hívásokhoz
- Batch processing: 3 hirdetés/LLM hívás
- Strukturált JSON kimenet
- **Cache mentés**: Eredmények automatikus tárolása 48h TTL-lel
- Hibakezelés és újrapróbálás

### 3. Eredmény Mentés
- Releváns hirdetések: `core_layer_filtered.parquet`
- Irreleváns hirdetések: `core_layer_irrelevant.parquet`
- LLM döntések logja: `llm_decisions_log.csv`

### 4. ML Modell Tréning
- Feature engineering
- Modell összehasonlítás (XGBoost vs Random Forest)
- Legjobb modell mentése pickle formátumban

## API Végpontok

| Endpoint | Metódus | Leírás |
|----------|---------|--------|
| `/` | GET | Főoldal |
| `/run-pipeline` | POST | Adatfeldolgozás indítása |
| `/stats` | GET | Statisztikák megjelenítése |
| `/data` | GET | Adattábla böngészés |
| `/map` | GET | Interaktív térkép |
| `/price-trends` | GET | Ártrend elemzés oldal |
| `/analyze-trends` | POST | Ártrend számítás |
| `/prediction` | GET/POST | ML predikció |
| `/query` | GET | Lekérdezés felület |
| `/sql-query` | POST | SQL lekérdezés |
| `/chat-query` | POST | Természetes nyelvi lekérdezés |
| `/admin/cache` | GET | Cache admin felület |
| `/admin/cache/stats` | GET | Cache statisztikák JSON |
| `/admin/cache/clear` | POST | Cache teljes törlése |

## Konfiguráció

### Környezeti Változók
- `WORKSPACE_DIR`: Munkaterület elérési útvonal
- `OLLAMA_GPU_LAYERS`: GPU rétegek száma
- `MODEL_NAME`: Használt LLM modell neve

### Parquet Fájl Formátum
```
Kötelező oszlopok:
- article_id: Egyedi hirdetésazonosító
- description: Hirdetés szövege
- price_huf: Ár forintban
- area_sqm: Terület négyzetméterben
- district: Budapesti kerület
- delivery_day: Hirdetés dátuma
```

## Fejlesztői Információk

### Teljesítmény Optimalizációk

#### 💾 Cache Rendszer
- **SHA256 hash alapú cache**: Azonos leírások automatikus felismerése
- **48 órás TTL**: Automatikus cache tisztítás
- **Redis backend**: Gyors, perzisztens tárolás
- **Cache statisztikák**: Real-time hit rate monitoring

#### 🚀 Feldolgozási Optimalizációk
- **Két-fázisú pipeline**: Worker előszűrés (0-50%) + LLM batch (50-100%)
- **Batch processing**: 3 hirdetés/LLM hívás csökkenti a hálózati overhead-et
- **Async I/O**: aiohttp + asyncio aszinkron LLM hívásokhoz
- **ThreadPoolExecutor**: Párhuzamos batch feldolgozás
- **Real-time progress tracking**: Socket.IO WebSocket-en keresztül
- **localStorage persistence**: Task folytatás oldal frissítés után

#### 📊 Monitoring
- Task Manager Redis-based állapotkövetés
- Worker és App komponens külön loggolás
- Cache HIT/MISS események real-time nyomon követése
- Feldolgozás végén részletes cache report

### Kód Stílus
- PEP 8 Python stíluskövetés
- Type hints használata
- Docstring dokumentáció
- Error handling minden külső híváshoz

### Adatvalidáció és Séma Kezelés
- **Pydantic modellek** LLM kimenetek strukturált validációjához
- **Pandera sémák** Parquet fájlok beolvasási validációhoz
- **Szigorú JSON parsing** LLM hallucináció elleni védekezéshez
- **Input sanitization** SQL injection és XSS támadások ellen
- **Data quality checks** automatikus adattisztasági riportokkal

### Testing
```bash
# Unit tesztek futtatása
python -m pytest tests/

# Integration tesztek
docker-compose -f docker-compose.test.yml up
```

### Debugging
- Flask development mód: `FLASK_DEBUG=1`
- Ollama debug logok: `docker-compose logs ollama`
- Alkalmazás logok: `docker-compose logs app`

## Hibaelhárítás

### Gyakori Problémák

1. **"Kevés adat az elemzéshez" hiba**
   - Ellenőrizd a kerület neveket az adatbázisban
   - Csökkentsd a lookback_months értéket

2. **GPU nem elérhető**
   - NVIDIA Docker toolkit telepítés
   - Docker daemon újraindítás

3. **Out of Memory**
   - Csökkentsd a batch_size értéket
   - Több RAM allokálás Docker-hez

4. **Lassú LLM válaszidő**
   - GPU használat engedélyezése
   - Kisebb modell választás
   - Kétlépcsős szűrés implementálása

5. **Gateway Timeout adatfeldolgozás közben**
   - Háttérfeladat-kezelő implementálása (RQ/Celery)
   - Progress tracking és státusz végpontok
   - Aszinkron feldolgozás WebSocket-ekkel

6. **LLM JSON parsing hibák**
   - Pydantic validáció implementálása
   - Retry mechanizmus hibás JSON esetén
   - Fallback szabályalapú kategorizálás

### Log Fájlok
- `llm_decisions_log.csv`: LLM döntések
- Docker logs: `docker-compose logs`

## Teljesítmény Optimalizálás

### LLM Optimalizálás
- **GPU használat maximalizálása** CUDA támogatással
- **Kétlépcsős szűrés**: Szabályalapú előszűrés a "szürke zónás" hirdetések LLM-hez küldése előtt
- **Batch processing**: Hirdetések kötegelése nagyobb throughput-ért (context window limitek figyelembevételével)
- **Model caching** Ollama-ban gyakran használt promptokhoz
- **Párhuzamos feldolgozás** ThreadPoolExecutor-ral optimális thread számmal
- **Intelligens retry logika** átmeneti LLM hibák kezelésére

### Adatbázis Optimalizálás
- Parquet particionálás dátum alapján
- DuckDB indexek használata
- Memóriában tartott gyakori lekérdezések

## Jövőbeli Fejlesztések

### Kritikus Prioritás
- [ ] **Aszinkron feldolgozás** RQ/Celery háttérfeladatokkal
- [ ] **Progress tracking API** real-time státusz követéshez
- [ ] **Pydantic/Pandera validáció** robusztus adatkezeléshez
- [ ] **Kétlépcsős LLM szűrés** teljesítményoptimalizáláshoz

### Közepes Prioritás
- [ ] Apache Airflow integrálás ütemezett futtatásokhoz
- [ ] Redis cache réteg gyakori lekérdezésekhez
- [ ] WebSocket alapú real-time frissítések
- [ ] Batch LLM processing nagyobb throughput-ért

### Hosszútávú
- [ ] Elasticsearch teljes szöveges kereséshez
- [ ] A/B tesztelés különböző LLM modellekhez
- [ ] Kubernetes telepítés production környezethez
- [ ] Automated testing pipeline
- [ ] Monitoring és alerting (Prometheus/Grafana)

## Licenc és Közreműködés

Ez a projekt szabadon használható és módosítható. Közreműködést szívesen fogadunk!

### Közreműködési Útmutató
1. Fork-old a projektet
2. Készíts egy feature branch-et
3. Commitold a változásaidat
4. Nyiss pull request-et

## Kapcsolat

Ha kérdésed vagy problémád van, nyiss egy issue-t a GitHub repozitóriumban.

---

**Utolsó frissítés**: 2026. január 13.
**Verzió**: 1.0.0