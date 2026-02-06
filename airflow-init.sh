#!/bin/bash

# Airflow inicializációs script
# Ez a script az első indításkor inicializálja az Airflow adatbázist és létrehozza az admin felhasználót

set -e

echo "🚀 Airflow inicializálás..."

# Adatbázis inicializálás (csak első futtatáskor szükséges)
if [ ! -f "/opt/airflow/airflow.db" ]; then
    echo "📊 Adatbázis inicializálása..."
    airflow db init
    
    # Admin felhasználó létrehozása
    echo "👤 Admin felhasználó létrehozása..."
    airflow users create \
        --username admin \
        --firstname Admin \
        --lastname User \
        --role Admin \
        --email admin@example.com \
        --password admin
    
    echo "✅ Airflow inicializálás kész!"
else
    echo "ℹ️ Adatbázis már létezik, upgrade futtatása..."
    airflow db upgrade
fi

# DAG pool létrehozása (LLM hívások limitálásához)
echo "🏊 Pool létrehozása (llm_pool: max 2 parallel LLM task)..."
airflow pools set llm_pool 2 "LLM task pool - max 2 parallel"

echo "✅ Inicializálás befejezve!"
