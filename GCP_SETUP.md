# GCP Storage Integráció - Setup Útmutató

> Google Cloud Storage automatikus file szinkronizáció konfifgurálása

## 🎯 Áttekintés

Az alkalmazás képes automatikusan szinkronizálni a `core_data.parquet` fájlt a Google Cloud Storage-ból. Ez lehetővé teszi:

- **Verzió ellenőrzés**: Lokális vs. Cloud fájl összehasonlítása
- **Automatikus letöltés**: One-click frissítés az Admin Dashboardról
- **Backup és rollback**: Hibás letöltés esetén visszaállítás

---

## 📋 Előfeltételek

1. **Google Cloud Platform Account**: [console.cloud.google.com](https://console.cloud.google.com)
2. **Létező GCP Projekt**: pl. `thesis-work-474807`
3. **Cloud Storage Bucket**: pl. `ingatlan-core-eu`

---

## 🔑 Service Account Létrehozása

### 1. Navigálj az IAM & Admin oldalra

https://console.cloud.google.com/iam-admin/serviceaccounts?project=YOUR_PROJECT_ID

### 2. CREATE SERVICE ACCOUNT

**Részletek**:
- **Service account name**: `thesis-app-storage`
- **Service account ID**: `thesis-app-storage` (automatikus)
- **Description**: `Read access to ingatlan-core-eu bucket for thesis application`

Kattints: **CREATE AND CONTINUE**

### 3. Grant Access (Szerepkör hozzáadása)

**Role kiválasztása**:
- Keress rá: `Storage Object Viewer`
- Válaszd ki: **Storage Object Viewer**

Ez csak **olvasási jogot** ad a bucket-ekhez (biztonságosabb, mint Owner).

Kattints: **CONTINUE** → **DONE**

### 4. JSON Kulcs Letöltése

1. Kattints a létrehozott service accountra (pl. `thesis-app-storage@thesis-work-474807.iam.gserviceaccount.com`)
2. Menj a **KEYS** fülre
3. **ADD KEY** → **Create new key**
4. Key type: **JSON**
5. **CREATE**

A fájl automatikusan letöltődik (pl. `thesis-work-474807-d60c5ba9a8d4.json`)

---

## 📁 JSON Kulcs Telepítése

### Fájl Átnevezése és Elhelyezése

```bash
# Windows PowerShell
cd C:\Users\YourName\Downloads\thesis_project
cp C:\Users\YourName\Downloads\thesis-work-474807-*.json .\gcp-credentials.json

# Linux/Mac
cd ~/thesis_project
cp ~/Downloads/thesis-work-474807-*.json ./gcp-credentials.json
```

**FONTOS**: A fájl neve PONTOSAN `gcp-credentials.json` legyen a projekt gyökérben!

---

## 🐳 Docker Konfiguráció

A `docker-compose.yml` már tartalmazza a szükséges konfigurációt:

```yaml
app:
  volumes:
    - ./gcp-credentials.json:/workspace/gcp-credentials.json:ro  # Read-only mount
  environment:
    - GOOGLE_APPLICATION_CREDENTIALS=/workspace/gcp-credentials.json
```

**Magyarázat**:
- `./gcp-credentials.json`: Host gépen lévő fájl
- `/workspace/gcp-credentials.json`: Konténeren belüli path
- `:ro`: Read-only (biztonság miatt)
- `GOOGLE_APPLICATION_CREDENTIALS`: Python google-cloud-storage library ezt a környezeti változót keresi

---

## ✅ Tesztelés

### 1. Konténerek Újraindítása

```bash
docker-compose stop app
docker-compose up -d app
```

### 2. Credentials Ellenőrzése

```bash
# Fájl elérhetősége a konténerben
docker exec thesis_project-app-1 ls -la /workspace/gcp-credentials.json

# Környezeti változó beállítása
docker exec thesis_project-app-1 printenv GOOGLE_APPLICATION_CREDENTIALS

# GCP kapcsolat tesztelése
docker exec thesis_project-app-1 python -c "from google.cloud import storage; client = storage.Client(); print('GCP Connection OK!')"
```

**Sikeres kimenet**:
```
-rwxrwxrwx 1 root root 2378 Feb  4 12:11 /workspace/gcp-credentials.json
/workspace/gcp-credentials.json
GCP Connection OK!
```

### 3. Admin Dashboard Teszt

1. Nyisd meg: http://localhost:5001/admin
2. Jelentkezz be: `admin` / `SzuperTitkosJelszo2025!`
3. Scroll le a **"☁️ GCP Adatfrissítés"** szekcióhoz
4. Kattints: **"🔍 Frissítés Ellenőrzése"**

**Sikeres eredmény**:
```
Modul: ☁️ GCP
Állapot: ✅ OK
Válaszidő: 408 ms
Részletek: Bucket elérhető - Fájl: 18.1 MB
```

---

## 🔒 Biztonság

### .gitignore Beállítások

A `.gitignore` fájl már tartalmazza:

```gitignore
# GCP Credentials (SENSITIVE!)
gcp-credentials.json
*-credentials.json
*.json.backup
```

**Ez biztosítja, hogy a credentials NE kerüljenek GitHub-ra!**

### Ajánlott Gyakorlatok

1. **NE commitáld** a JSON kulcsot
2. **Különböző kulcsok**: Dev/Prod környezetekhez külön service accountok
3. **Kulcs rotáció**: 90 naponként új kulcs generálása
4. **Minimum jogosultságok**: Csak `Storage Object Viewer`, NE `Owner`
5. **Audit logok**: GCP Console-ban ellenőrizd a hozzáféréseket

---

## 🐛 Troubleshooting

### "Your default credentials were not found"

**Probléma**: Python könyvtár nem találja a credentials-t

**Megoldás**:
```bash
# 1. Ellenőrizd a környezeti változót
docker exec thesis_project-app-1 printenv GOOGLE_APPLICATION_CREDENTIALS

# 2. Ha üres, indítsd újra a konténert
docker-compose stop app && docker-compose up -d app

# 3. Ha továbbra is hiba van, ellenőrizd a fájl létezését
docker exec thesis_project-app-1 cat /workspace/gcp-credentials.json | head -n 5
```

### "Bucket elérhető" helyett "Hiba" üzenet

**Lehetséges okok**:
1. Service account nincs hozzáadva a bucket-hez
2. Helytelen bucket név (`GCP_BUCKET_NAME` a webapp.py-ban)
3. Hálózati probléma

**Megoldás**:
```bash
# Bucket név ellenőrzése a kódban
docker exec thesis_project-app-1 grep GCP_BUCKET_NAME /workspace/app/webapp.py

# Manuális gsutil teszt (ha telepítve van a hostgépen)
gsutil ls -l gs://ingatlan-core-eu/core_data.parquet
```

### Fájl letöltés megszakad

**Probléma**: Hálózati timeout vagy túl nagy fájl

**Megoldás**:
```python
# webapp.py - növeld a timeout-ot
storage_client = storage.Client(timeout=600)  # 10 perc
```

---

## 📚 További Információk

### GCP Dokumentáció
- [Authentication Overview](https://cloud.google.com/docs/authentication)
- [Service Account Best Practices](https://cloud.google.com/iam/docs/best-practices-service-accounts)
- [Python Storage Client Library](https://cloud.google.com/python/docs/reference/storage/latest)

### Költségek
- **Storage**: ~$0.020/GB/hó (Standard tier)
- **Network egress**: Első 1GB ingyenes havonta
- **Operations**: Class A (write) $0.05/10k ops, Class B (read) $0.004/10k ops

**Becsült költség 18MB fájlhoz + havi 100 letöltés**: ~$0.10/hó

---

**Utolsó frissítés**: 2026. február 4.
