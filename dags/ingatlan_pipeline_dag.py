"""
Airflow DAG a Budapest Ingatlan LLM Adatfeldolgozáshoz

Ez a DAG koordinálja a teljes feldolgozási pipeline-t:
1. Adatbetöltés (Parquet streaming)
2. ML Worker előszűrés (TF-IDF)
3. LLM batch elemzés (Ollama)
4. Eredmény mentés
5. ML modell tréning (XGBoost/Random Forest)

Automatikus ütemezés: Naponta egyszer, vagy manuális trigger
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import datetime, timedelta
import sys
import os

# Projekt könyvtár hozzáadása a Python path-hoz
sys.path.insert(0, '/workspace/app')

default_args = {
    'owner': 'admin',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=3),
}

# Task függvények importálása
def load_and_validate_data(**context):
    """1. FELADAT: Adatbetöltés és validálás"""
    from parquet_streaming import ParquetStreamReader, get_unique_articles_streaming
    from models import validate_dataframe_schema
    import pandas as pd
    
    print("📂 Parquet fájl betöltése...")
    INPUT_FILE = '/workspace/parquet/core_data.parquet'
    
    # Unique articles kinyerése streaming módon
    unique_articles = get_unique_articles_streaming(INPUT_FILE, chunk_size=50000)
    
    print(f"✅ {len(unique_articles)} egyedi cikk betöltve")
    
    # XCom-ba mentés (következő taskokhoz)
    # Convert datetime columns to strings for JSON serialization
    sample = unique_articles[:100].copy()
    for col in sample.select_dtypes(include=['datetime64']).columns:
        sample[col] = sample[col].astype(str)
    
    context['task_instance'].xcom_push(key='total_articles', value=len(unique_articles))
    context['task_instance'].xcom_push(key='articles_sample', value=sample.to_dict('records'))
    
    return len(unique_articles)


def ml_worker_filter(**context):
    """2. FELADAT: ML Worker előszűrés (TF-IDF)"""
    from ml_worker_filter import get_ml_filter, train_ml_filter_from_llm_log
    from parquet_streaming import ParquetStreamReader, get_unique_articles_streaming
    import pandas as pd
    
    print("🎯 ML Worker Filter inicializálása...")
    
    # Modell tréning LLM log alapján
    ml_trained = train_ml_filter_from_llm_log()
    if not ml_trained:
        print("⚠️ ML filter inaktív - nincs elég tréningadat")
        return {'status': 'skipped', 'filtered_count': 0}
    
    # Adatok betöltése
    INPUT_FILE = '/workspace/parquet/core_data.parquet'
    unique_articles = get_unique_articles_streaming(INPUT_FILE, chunk_size=50000)
    
    # ML előszűrés
    ml_filter = get_ml_filter()
    filtered_articles = []
    
    for idx, article in unique_articles.iterrows():
        description = str(article.get('description', ''))
        is_relevant, confidence = ml_filter.predict(description)
        
        if is_relevant:
            filtered_articles.append(article)
    
    filtered_df = pd.DataFrame(filtered_articles)
    
    print(f"✅ ML szűrés: {len(filtered_articles)}/{len(unique_articles)} cikk továbbjutott")
    
    # Eredmény mentése ideiglenes fájlba
    temp_file = '/workspace/temp_ml_filtered.parquet'
    filtered_df.to_parquet(temp_file, index=False)
    
    # XCom-ba mentés
    context['task_instance'].xcom_push(key='ml_filtered_count', value=len(filtered_articles))
    context['task_instance'].xcom_push(key='temp_file', value=temp_file)
    
    return {'status': 'success', 'filtered_count': len(filtered_articles)}


def llm_batch_processing(**context):
    """3. FELADAT: LLM Batch feldolgozás (Ollama)"""
    import pandas as pd
    import ollama
    import json
    from llm_cache import get_cached_result, set_cached_result, get_cache_stats
    
    print("🤖 LLM Batch feldolgozás indítása...")
    
    # ML szűrt adatok betöltése
    temp_file = context['task_instance'].xcom_pull(key='temp_file', task_ids='ml_worker_filter')
    if not temp_file:
        print("⚠️ ML szűrés kihagyva - teljes adatból dolgozunk")
        temp_file = '/workspace/parquet/core_data.parquet'
    
    df = pd.read_parquet(temp_file)
    
    # 🧪 TESZT MÓD: Csak első 500 cikk (teljes futáshoz távolítsd el ezt a sort)
    TEST_LIMIT = 500
    if len(df) > TEST_LIMIT:
        print(f"⚠️ TESZT MÓD: Csak első {TEST_LIMIT} cikket dolgozunk fel a {len(df)}-ből")
        df = df.head(TEST_LIMIT)
    
    # LLM feldolgozás cikkenként
    print(f"🔄 {len(df)} cikk LLM elemzése...")
    
    MODEL_NAME = 'llama3.2:3b'
    PROMPT_TEMPLATE = """Elemezd ezt a budapesti ingatlanhirdetést. Releváns-e lakásvásárláshoz?
    
Irreleváns CSAK ha: tulajdoni hányad, bérleti jog, haszonélvezet, önkormányzati, csere, nem budapesti.

Leírás: {description}

Válasz JSON formátumban: {{"relevant": true/false, "reason": "indoklás"}}"""
    
    relevant_articles = []
    irrelevant_articles = []
    
    for idx, row in df.iterrows():
        description = str(row.get('description', ''))
        article_id = row.get('article_id', idx)
        
        # Cache ellenőrzés
        cached = get_cached_result(description)
        
        if cached:
            result = cached
        else:
            # LLM hívás
            try:
                prompt = PROMPT_TEMPLATE.format(description=description[:1000])
                response = ollama.chat(
                    model=MODEL_NAME,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                
                # JSON parse with robust error handling
                content = response['message']['content'].strip()
                
                # Remove markdown code blocks if present
                if content.startswith('```'):
                    content = content.split('```')[1]
                    if content.startswith('json'):
                        content = content[4:].strip()
                
                # Extract JSON object from text
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if json_match:
                    content = json_match.group(0)
                
                result = json.loads(content)
                
                # Cache-elés (description használata, nem article_id!)
                set_cached_result(description, result)
                
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON parse hiba cikknél {article_id}: {str(e)}")
                print(f"   LLM válasz: {content[:100]}")
                result = {'relevant': True, 'reason': 'JSON parse hiba - alapértelmezett releváns'}
            except Exception as e:
                print(f"⚠️ LLM hiba cikknél {article_id}: {str(e)}")
                result = {'relevant': True, 'reason': 'LLM hiba - alapértelmezett releváns'}
        
        # Eredmény hozzáadása az eredeti adatokhoz
        row_dict = row.to_dict()
        row_dict.update(result)
        
        if result.get('relevant', True):
            relevant_articles.append(row_dict)
        else:
            irrelevant_articles.append(row_dict)
        
        # Progress log minden 100. cikknél
        if (idx + 1) % 100 == 0:
            print(f"  ... {idx + 1}/{len(df)} feldolgozva")
    
    print(f"✅ LLM elemzés kész: {len(relevant_articles)} releváns, {len(irrelevant_articles)} irreleváns")
    
    # Mentés Parquet fájlokba
    OUTPUT_FILE = '/workspace/parquet/core_layer_filtered.parquet'
    IRRELEVANT_FILE = '/workspace/parquet/core_layer_irrelevant.parquet'
    
    if relevant_articles:
        pd.DataFrame(relevant_articles).to_parquet(OUTPUT_FILE, index=False)
        print(f"💾 Releváns adatok mentve: {OUTPUT_FILE}")
    
    if irrelevant_articles:
        pd.DataFrame(irrelevant_articles).to_parquet(IRRELEVANT_FILE, index=False)
        print(f"💾 Irreleváns adatok mentve: {IRRELEVANT_FILE}")
    
    # Cache statisztikák
    cache_stats = get_cache_stats()
    print(f"📊 Cache hit rate: {cache_stats.get('hit_rate', 0):.1f}%")
    
    # XCom-ba mentés
    context['task_instance'].xcom_push(key='relevant_count', value=len(relevant_articles))
    context['task_instance'].xcom_push(key='irrelevant_count', value=len(irrelevant_articles))
    
    return {
        'relevant': len(relevant_articles),
        'irrelevant': len(irrelevant_articles),
        'cache_hit_rate': cache_stats.get('hit_rate', 0)
    }


def train_prediction_model(**context):
    """4. FELADAT: XGBoost/Random Forest modell tréning"""
    from train_model import train_and_evaluate_models
    import pandas as pd
    import json
    
    print("🎓 ML predikciós modellek tréningje...")
    
    # Releváns adatok betöltése
    INPUT_FILE = '/workspace/parquet/core_layer_filtered.parquet'
    
    try:
        df = pd.read_parquet(INPUT_FILE)
        print(f"📊 {len(df)} releváns hirdetés betöltve")
        
        # Modell tréning
        metrics = train_and_evaluate_models(df)
        
        print(f"✅ Modell tréning kész")
        print(f"📈 XGBoost RMSE: {metrics['xgboost']['rmse']:.2f}")
        print(f"📈 Random Forest RMSE: {metrics['random_forest']['rmse']:.2f}")
        
        # Metrikák mentése
        with open('/workspace/model_metrics.json', 'w') as f:
            json.dump(metrics, f, indent=2)
        
        # XCom-ba mentés
        context['task_instance'].xcom_push(key='model_metrics', value=metrics)
        
        return metrics
        
    except Exception as e:
        print(f"❌ Hiba a modell tréning során: {e}")
        return {'status': 'failed', 'error': str(e)}


def cleanup_temp_files(**context):
    """5. FELADAT: Ideiglenes fájlok törlése"""
    import os
    
    print("🧹 Ideiglenes fájlok törlése...")
    
    temp_files = [
        '/workspace/temp_ml_filtered.parquet',
    ]
    
    for file_path in temp_files:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"🗑️ Törölve: {file_path}")
    
    return {'status': 'cleanup_complete'}


# ============================================================================
# DAG DEFINÍCIÓ
# ============================================================================

with DAG(
    'ingatlan_llm_pipeline',
    default_args=default_args,
    description='Budapest Ingatlan LLM Adatfeldolgozás',
    schedule_interval='@daily',  # Naponta egyszer automatikus futtatás
    start_date=days_ago(1),
    catchup=False,  # Ne futtassa le a múltbeli napokat
    tags=['ingatlan', 'llm', 'data-processing'],
    max_active_runs=1,  # Csak 1 pipeline futhat egyszerre
) as dag:
    
    # 1. Adatbetöltés
    load_data_task = PythonOperator(
        task_id='load_and_validate_data',
        python_callable=load_and_validate_data,
        provide_context=True,
    )
    
    # 2. ML Worker előszűrés
    ml_filter_task = PythonOperator(
        task_id='ml_worker_filter',
        python_callable=ml_worker_filter,
        provide_context=True,
        pool='llm_pool',  # Resource pool (max 2 parallel LLM task)
    )
    
    # 3. LLM Batch feldolgozás
    llm_processing_task = PythonOperator(
        task_id='llm_batch_processing',
        python_callable=llm_batch_processing,
        provide_context=True,
        pool='llm_pool',
        execution_timeout=timedelta(hours=2),
    )
    
    # 4. ML Modell tréning
    train_model_task = PythonOperator(
        task_id='train_prediction_model',
        python_callable=train_prediction_model,
        provide_context=True,
    )
    
    # 5. Cleanup
    cleanup_task = PythonOperator(
        task_id='cleanup_temp_files',
        python_callable=cleanup_temp_files,
        provide_context=True,
        trigger_rule='all_done',  # Mindig fusson, függetlenül az előző taskok állapotától
    )
    
    # Task függőségek (DAG sorrend)
    load_data_task >> ml_filter_task >> llm_processing_task >> train_model_task >> cleanup_task
