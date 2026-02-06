# GCP Storage Integráció Beállítása

## Áttekintés
Az alkalmazás most már képes letölteni a `core_data.parquet` fájlt a Google Cloud Storage-ból.

**Bucket:** `ingatlan-core-eu`  
**Fájl:** `core_data.parquet`

## Beállítási Lépések

### 1. Service Account Kulcs Letöltése

1. Lépj be a GCP Console-ra: https://console.cloud.google.com
2. Navigálj: **IAM & Admin** → **Service Accounts**
3. Válaszd ki vagy hozz létre egy Service Account-ot (például `thesis-app-sa`)
4. Kattints a **Keys** fülre
5. **Add Key** → **Create new key** → **JSON**
6. Mentsd le a fájlt `gcp-service-account.json` néven

### 2. Jogosultságok Beállítása

A Service Account-nak rendelkeznie kell:
- **Storage Object Viewer** szerepkörrel a `ingatlan-core-eu` bucket-hez

```bash
# GCP CLI parancs (opcionális):
gcloud projects add-iam-policy-binding thesis-work-474807 \
    --member="serviceAccount:thesis-app-sa@thesis-work-474807.iam.gserviceaccount.com" \
    --role="roles/storage.objectViewer"
```

### 3. Credentials Beállítása Docker-ben

#### Opció A: Environment változó (Ajánlott)

Másold a service account JSON fájlt a projekt gyökérbe:
```bash
cp /path/to/gcp-service-account.json ./gcp-credentials.json
```

Frissítsd a `docker-compose.yml`-t:
```yaml
services:
  app:
    environment:
      - GOOGLE_APPLICATION_CREDENTIALS=/workspace/gcp-credentials.json
    volumes:
      - ./gcp-credentials.json:/workspace/gcp-credentials.json:ro
```

#### Opció B: Volume mount

```yaml
services:
  app:
    environment:
      - GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-key.json
    volumes:
      - ./gcp-service-account.json:/secrets/gcp-key.json:ro
```

### 4. Újraindítás

```bash
docker-compose down
docker-compose up -d
```

## Használat

### Admin Dashboard-on

1. Navigálj: http://localhost:5001/admin (admin/admin)
2. Keresd a **☁️ GCP Adatfrissítés** szekciót
3. Kattints: **🔍 Frissítés Ellenőrzése**
4. Ha újabb verzió érhető el: **⬇️ Letöltés GCP-ből**
5. A letöltés után: **🚀 Adatfeldolgozás Indítása**

### API Endpoint-ok

**Verzió ellenőrzése:**
```bash
curl http://localhost:5001/admin/gcp/check-update
```

**Letöltés:**
```bash
curl -X POST http://localhost:5001/admin/gcp/download
```

## Hibaelhárítás

### "Google Cloud Storage könyvtár nincs telepítve"
```bash
docker exec thesis_project-app-1 pip install google-cloud-storage
# VAGY
docker-compose build app
docker-compose up -d app
```

### "Credentials not found"
Ellenőrizd:
1. A JSON fájl létezik és olvasható
2. A `GOOGLE_APPLICATION_CREDENTIALS` környezeti változó helyesen van beállítva
3. A Docker volume mount működik

```bash
docker exec thesis_project-app-1 ls -la /workspace/gcp-credentials.json
docker exec thesis_project-app-1 env | grep GOOGLE
```

### "Permission denied" hiba
A Service Account-nak nincs joga a bucket-hez:
```bash
gsutil iam ch serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com:objectViewer gs://ingatlan-core-eu
```

## Biztonság

⚠️ **FONTOS:**
- A `gcp-service-account.json` tartalmazza a privát kulcsokat!
- Add hozzá a `.gitignore`-hoz: `gcp-*.json`
- Production környezetben használj Secret Manager-t

```bash
echo "gcp-*.json" >> .gitignore
```

## Workflow

1. ☁️ **GCP Check** → Ellenőrzi van-e újabb fájl
2. ⬇️ **Download** → Letölti a `core_data.parquet`-et
3. 🚀 **Pipeline** → Airflow DAG elindítása
4. 📊 **Processing** → LLM elemzés (6-8 óra)
5. 🎓 **Train Model** → ML modell tanítása
6. ✅ **Done** → Predikciók elérhetőek

## Tesztelés

```python
# Python tesztkód
from google.cloud import storage

client = storage.Client()
bucket = client.bucket('ingatlan-core-eu')
blob = bucket.blob('core_data.parquet')
print(f"Size: {blob.size / 1024 / 1024:.2f} MB")
print(f"Updated: {blob.updated}")
```
