"""
Háttérfeladatok végrehajtása aszinkron módon.
Ez a modul tartalmazza az adatfeldolgozási logikát RQ worker számára.
"""

import pandas as pd
import ollama
import json
import os
import re
import sys
import asyncio
import aiohttp
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Dict, Any, List
from task_manager import TaskManager
from models import sanitize_llm_output, validate_dataframe_schema, PropertyInput
from llm_cache import get_cached_result, set_cached_result, get_cache_stats, test_cache_connection
from ml_worker_filter import get_ml_filter, train_ml_filter_from_llm_log
from parquet_streaming import (
    ParquetStreamReader, 
    get_unique_articles_streaming, 
    estimate_parquet_memory
)
from connection_pool import get_ollama_session, get_connection_pool_stats
from incremental_processing import get_incremental_processor

# Constants
MODEL_NAME = os.getenv('LLM_MODEL', 'llama3.2:3b')
INPUT_FILE = '/workspace/core_data.parquet'
OUTPUT_FILE = '/workspace/parquet/core_layer_filtered.parquet'
IRRELEVANT_OUTPUT_FILE = '/workspace/parquet/core_layer_irrelevant.parquet'
LOG_FILE = '/workspace/llm_decisions_log.csv'

# 🧪 TESZT MÓD: Csak első 100 hirdetést dolgozza fel (True = teszt, False = teljes)
TEST_MODE = True
TEST_LIMIT = 100

# Batch LLM feldolgozáshoz (3 cikk egyszerre)
BATCH_PROMPT_TEMPLATE = """
Elemezd az alábbi {count} budapesti ingatlanhirdetést lakásvásárlás szempontjából.
FONTOS: Mindegyiket KÜLÖN-KÜLÖN értékeld, ne keverd őket össze!

CIKK #1:
ID: {id_1}
Leírás: {desc_1}

CIKK #2:
ID: {id_2} 
Leírás: {desc_2}

CIKK #3:
ID: {id_3}
Leírás: {desc_3}

Szempontok:
- Releváns: Lakás, társasházi lakás, családi ház, ikerház Budapesten - fővárosban lakásvevőknek érdekes
- Irreleváns: Tulajdoni hányad, nyaraló, telek, garázs, üzlethelyiség, kerülendő konstrukciók

VÁLASZFORMÁTUM (JSON array, pontosan 3 elem):
[
  {{"id": "{id_1}", "relevant": true, "reason": "rövid indoklás", "floor": null, "street": null, "building_type": null, "property_category": null, "has_terrace": null}},
  {{"id": "{id_2}", "relevant": false, "reason": "rövid indoklás", "floor": null, "street": null, "building_type": null, "property_category": null, "has_terrace": null}},
  {{"id": "{id_3}", "relevant": true, "reason": "rövid indoklás", "floor": null, "street": null, "building_type": null, "property_category": null, "has_terrace": null}}
]
"""

# Egyedi cikk feldolgozáshoz (fallback)
PROMPT_TEMPLATE = """
Feladat: Ingatlanleírás alapján döntsd el a relevanciát és nyerd ki a strukturált adatokat.
Alapértelmezés: Az ingatlan releváns (true), kivéve, ha kizáró okot találsz.

Kizáró okok (`relevant: false`):
- Nem 1/1 tulajdon vagy nem tiszta eladás (pl. osztatlan közös, tulajdoni hányad, bérleti jog, haszonélvezet, önkormányzati, csere).
- Ingatlan típusa: Kizáró ok, ha NEM lakás célú (telek, garázs, nyaraló, üdülő NEM releváns). Lakás, családi ház, ikerház Budapesten RELEVÁNS.
- Nem budapesti.
- "Csak készpénzes vevőknek" (ez gyakran jogi problémát jelez).

Strukturált adatok:
- Emelet (`floor`): Szám (pl. 1, 2). Földszint: 0. Szuterén/félszuterén: -1. Ha nincs info: null.
- Utca (`street`): Az ingatlan utcaneve (pl. 'Kossuth Lajos utca'). Ha nincs: null.
- Építési mód (`building_type`): "tegla" ha tégla épület, "panel" ha panelház, "egyeb" ha más (pl. vályog, favázas), null ha nincs info.
- Ingatlan kategória (`property_category`): "lakas" vagy "haz". A társasházi lakás = "lakas". Ha nincs info: null.
- Terasz (`has_terrace`): true ha van terasz/erkély/loggia/franciaerkély, false ha nincs vagy nem említi, null ha nem egyértelmű.

Leírás: {description}

Formátum: A válaszod CSAK egy JSON objektum legyen, extra szöveg nélkül.
Példa: {{"relevant": true, "reason": "", "floor": 1, "street": "Egészségház utca", "building_type": "tegla", "property_category": "lakas", "has_terrace": true}}
vagy {{"relevant": false, "reason": "Családi ház", "floor": null, "street": null, "building_type": null, "property_category": "haz", "has_terrace": null}}
"""

# Fejlett szabályalapú szűrés - kétlépcsős megközelítéssel
DEFINITELY_IRRELEVANT_KEYWORDS = {
    "tulajdoni hányad": "Tulajdoni hányad", 
    "bérleti jog": "Bérleti jog (nem eladás)",
    "önkormányzati ingatlan": "Önkormányzati ingatlan",
    "ingatlancsere": "Ingatlancsere (nem eladás)",
    "cserélhető": "Csere (nem eladás)",
    "cserélném": "Csere (nem eladás)",
    "haszonélvezet": "Haszonélvezet",
    "haszonélvezettel": "Haszonélvezet",
}

LIKELY_IRRELEVANT_KEYWORDS = {
    # Üres - minden más ingatlan típus engedélyezett (ikerház, családi ház, üzlet, iroda, nyaraló)
}

NEGATION_KEYWORDS = [
    "tehermentes", "per- és tehermentes", "per és tehermentes",
    "nincs haszonélvezet", "törölve", "megszüntetve",
    "nincs", "nem terhelt", "teljes tulajdon", "1/1 tulajdon",
    "magántulajdon", "magánszemély tulajdonban"
]

# ============================================================================
# ASYNC LLM HÍVÁSOK AIOHTTP-VAL
# ============================================================================

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434')  # Docker belső hálózaton

async def async_ollama_chat(session: aiohttp.ClientSession, prompt: str, model: str = MODEL_NAME) -> Dict[str, Any]:
    """
    Aszinkron LLM hívás aiohttp-val.
    
    Args:
        session: aiohttp ClientSession
        prompt: Az LLM-nek küldött prompt
        model: A használt model neve
        
    Returns:
        Az LLM válasza dictionary formában
    """
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0}
    }
    
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as response:
            response.raise_for_status()
            result = await response.json()
            return result
    except asyncio.TimeoutError:
        raise Exception(f"LLM hívás timeout (300s) - model: {model}")
    except aiohttp.ClientError as e:
        raise Exception(f"LLM hívás hiba: {e}")

async def async_get_batch_llm_decision(session: aiohttp.ClientSession, articles_batch: List[pd.Series]) -> List[Dict[str, Any]]:
    """
    Aszinkron batch LLM feldolgozás 3 cikkhez.
    
    Args:
        session: aiohttp ClientSession
        articles_batch: 3 cikk listája
        
    Returns:
        Lista a 3 cikk eredményével
    """
    if len(articles_batch) != 3:
        raise ValueError("Batch size must be exactly 3")
    
    try:
        combined_texts = []
        article_ids = []
        
        for article in articles_batch:
            article_id = article['article_id']
            description = article.get('description', '') or ''
            title = article.get('title', '') or ''
            combined_text = f"{title} {description}".strip()
            
            combined_texts.append(combined_text)
            article_ids.append(article_id)
        
        prompt = BATCH_PROMPT_TEMPLATE.format(
            count=3,
            id_1=article_ids[0], desc_1=combined_texts[0],
            id_2=article_ids[1], desc_2=combined_texts[1], 
            id_3=article_ids[2], desc_3=combined_texts[2]
        )
        
        print(f"🚀 ASYNC BATCH LLM hívás: {article_ids}", flush=True)
        
        # Async LLM hívás
        response = await async_ollama_chat(session, prompt)
        content = response['message']['content']
        
        # JSON array parsing
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            raise ValueError("Nem található JSON array a válaszban")
        
        results_array = json.loads(json_match.group(0))
        
        if len(results_array) != 3:
            raise ValueError(f"Várt 3 eredmény, kapott: {len(results_array)}")
        
        # Validálás
        from models import LLMResponse
        validated_results = []
        for result in results_array:
            try:
                validated = LLMResponse(**result)
                validated_results.append(validated.dict())
            except Exception as e:
                validated_results.append({
                    "relevant": False, 
                    "reason": f"Validációs hiba: {str(e)}", 
                    "floor": None, "street": None, "building_type": None, 
                    "property_category": None, "has_terrace": None
                })
        
        print(f"✅ ASYNC BATCH eredmény: {len(validated_results)} cikk", flush=True)
        return validated_results
        
    except Exception as e:
        print(f"❌ ASYNC BATCH hiba: {e} - Fallback egyenkénti feldolgozásra", flush=True)
        # Fallback: egyenkénti feldolgozás
        individual_results = []
        for article in articles_batch:
            individual_result = await async_get_llm_decision_with_validation(
                session,
                f"{article.get('title', '')} {article.get('description', '')}".strip()
            )
            individual_results.append(individual_result)
        return individual_results

async def async_get_llm_decision_with_validation(session: aiohttp.ClientSession, description: str) -> Dict[str, Any]:
    """
    Aszinkron LLM hívás egyedi cikk elemzéséhez cache-eléssel.
    
    Args:
        session: aiohttp ClientSession
        description: Az ingatlanhirdetés leírása
        
    Returns:
        Dict az LLM döntéssel és strukturált adatokkal
    """
    # 1. Cache ellenőrzés (szinkron)
    cached_result = get_cached_result(description)
    if cached_result:
        return cached_result
    
    # 2. LLM hívás aszinkron módon
    prompt = PROMPT_TEMPLATE.format(description=description)
    
    try:
        response = await async_ollama_chat(session, prompt)
        content = response['message']['content']
        
        # Sanitizált és validált kimenet
        from models import LLMResponse
        parsed_result = sanitize_llm_output(content)
        validated_result = LLMResponse(**parsed_result)
        result_dict = validated_result.dict()
        
        # 3. Cache mentés (szinkron)
        set_cached_result(description, result_dict)
        
        return result_dict
        
    except Exception as e:
        print(f"❌ ASYNC LLM hiba: {e}", flush=True)
        return {
            "relevant": False,
            "reason": f"LLM hívás sikertelen: {str(e)}",
            "floor": None, "street": None, "building_type": None,
            "property_category": None, "has_terrace": None
        }

# ============================================================================
# SZINKRON WRAPPER FÜGGVÉNYEK (backward compatibility)
# ============================================================================

def get_batch_llm_decision(articles_batch: List[pd.Series]) -> List[Dict[str, Any]]:
    """
    Szinkron wrapper az async_get_batch_llm_decision függvényhez.
    ThreadPoolExecutor-ral történő híváshoz.
    Minden batch saját session-nel rendelkezik az event loop problémák elkerülésére.
    """
    async def _run():
        # Optimalizált connector minden batch-hez
        connector = aiohttp.TCPConnector(
            limit=30,
            limit_per_host=30,
            force_close=False,
            keepalive_timeout=60,
        )
        timeout = aiohttp.ClientTimeout(total=300, connect=10, sock_read=300)
        
        # Új session a batch-hez
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'Connection': 'keep-alive'}
        ) as session:
            return await async_get_batch_llm_decision(session, articles_batch)
    
    # Új event loop létrehozása a thread-ben
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

def get_llm_decision_with_validation(description: str) -> Dict[str, Any]:
    """
    Szinkron wrapper az async_get_llm_decision_with_validation függvényhez.
    Minden hívás saját session-nel rendelkezik.
    """
    async def _run():
        # Optimalizált connector
        connector = aiohttp.TCPConnector(
            limit=10,
            force_close=False,
            keepalive_timeout=60,
        )
        timeout = aiohttp.ClientTimeout(total=300, connect=10, sock_read=300)
        
        # Új session
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'Connection': 'keep-alive'}
        ) as session:
            return await async_get_llm_decision_with_validation(session, description)
    
    # Új event loop létrehozása a thread-ben
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

def worker_filter_article(row: pd.Series) -> Dict[str, Any]:
    """
    Gyors worker előszűrés - csak eldönti hogy releváns-e vagy sem.
    Ha bizonytalan, akkor 'needs_llm' = True
    """
    try:
        # Input validáció
        property_input = PropertyInput(**row.to_dict())
        article_id = property_input.article_id
        description = property_input.description or ""
        title = property_input.title or ""
        
    except Exception as e:
        return {
            'article_id': row.get('article_id', 'unknown'),
            'relevant': False,
            'reason': f'Validációs hiba: {str(e)}',
            'needs_llm': False
        }
    
    # 1. Üres leírás → azonnal irreleváns
    if not description or len(description.strip()) < 20:
        return {
            'article_id': article_id,
            'relevant': False,
            'reason': 'Worker előszűrés: Üres vagy túl rövid leírás',
            'needs_llm': False
        }
    
    # 2. Kulcsszavas előszűrés → azonnal irreleváns  
    combined_text = f"{title} {description}".lower()
    
    # Speciális eset: osztatlan közös tulajdon CSAK ha törtszámmal (x/y rész)
    # Példa: "osztatlan közös tulajdon 475/1000-d része" → SZŰR
    # De: "osztatlan közös kertrész" → NEM SZŰR (releváns)
    osztatlan_pattern = r'osztatlan közös tulajdon.*?\d+/\d+'
    if re.search(osztatlan_pattern, combined_text):
        return {
            'article_id': article_id,
            'relevant': False,
            'reason': 'Worker előszűrés: Osztatlan közös tulajdon (törtszám)',
            'needs_llm': False
        }
    
    # Egyértelmű kizáró kulcsszavak
    for keyword, reason in DEFINITELY_IRRELEVANT_KEYWORDS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', combined_text):
            # Ellenőrizzük, hogy nincs-e negáció a közelben
            # Például: "nincs haszonélvezet", "tehermentes", "törölve"
            negated = False
            for negation in NEGATION_KEYWORDS:
                # Keresés 50 karakteres ablakban a kulcsszó előtt és után
                pattern = rf'.{{0,50}}\b{re.escape(negation)}\b.{{0,50}}\b{re.escape(keyword)}\b|\b{re.escape(keyword)}\b.{{0,50}}\b{re.escape(negation)}\b'
                if re.search(pattern, combined_text):
                    negated = True
                    break
            
            if not negated:
                return {
                    'article_id': article_id,
                    'relevant': False,
                    'reason': f'Worker előszűrés: {reason}',
                    'needs_llm': False
                }
    
    # 3. ML-alapú előszűrés KIKAPCSOLVA TESZT MÓDBAN
    # Csak a kulcsszavas szűrésre koncentrálunk
    # if len(description.strip()) < 100:
    #     return {
    #         'article_id': article_id,
    #         'relevant': None,  # Bizonytalan
    #         'reason': 'Worker: Rövid leírás - LLM pontos elemzésre vár',
    #         'needs_llm': True
    #     }
    # 
    # ml_filter = get_ml_filter()
    # if ml_filter.is_trained:
    #     ml_relevant, ml_confidence, ml_reason = ml_filter.predict(description)
    #     
    #     # Ha ML magabiztosan döntött → használjuk
    #     if ml_relevant is not None:
    #         return {
    #             'article_id': article_id,
    #             'relevant': ml_relevant,
    #             'reason': f'Worker ML szűrés: {ml_reason}',
    #             'needs_llm': False
    #         }
    #     # ML bizonytalan → LLM-re bízza
    
    # 4. Ha kulcsszavas szűrés nem döntött → LLM-re bízza
    return {
        'article_id': article_id,
        'relevant': None,  # Bizonytalan
        'reason': 'Worker nem tudta eldönteni - LLM szükséges',
        'needs_llm': True
    }

def process_article_with_llm(row: pd.Series) -> Dict[str, Any]:
    """LLM feldolgozás egy cikkhez (már worker által jóváhagyott)."""
    try:
        property_input = PropertyInput(**row.to_dict())
        article_id = property_input.article_id
        description = property_input.description or ""
        title = property_input.title or ""
        
    except Exception as e:
        return {
            'article_id': row.get('article_id', 'unknown'),
            'relevant': False,
            'reason': f'Validációs hiba: {str(e)}',
            'description': row.get('description', ''),
            'floor': None, 'street': None, 'building_type': None,
            'property_category': None, 'has_terrace': None
        }
    
    # LLM elemzés
    combined_text = f"{title} {description}"
    print(f"🤖 LLM elemzés: {article_id}", flush=True)
    llm_result = get_llm_decision_with_validation(combined_text)
    
    return {
        'article_id': article_id,
        'relevant': llm_result.get('relevant', False),
        'reason': f"LLM elemzés: {llm_result.get('reason', 'Nincs indoklás')}",
        'description': description,
        'filtered_by': 'llm',
        'floor': llm_result.get('floor'),
        'street': llm_result.get('street'),
        'building_type': llm_result.get('building_type'),
        'property_category': llm_result.get('property_category'),
        'has_terrace': llm_result.get('has_terrace')
    }

def process_article_enhanced(row: pd.Series, task_manager: TaskManager, task_id: str) -> Dict[str, Any]:
    """Továbbfejlesztett hirdetésfeldolgozás - DEPRECATED, használd a kétfázisú megközelítést!"""
    # Ez a funkció már nem használt, megtartjuk backward compatibility miatt
    worker_result = worker_filter_article(row)
    if not worker_result['needs_llm']:
        return {
            'article_id': worker_result['article_id'],
            'relevant': worker_result['relevant'],
            'reason': worker_result['reason'],
            'description': row.get('description', ''),
            'filtered_by': 'worker',
            'floor': None, 'street': None, 'building_type': None,
            'property_category': None, 'has_terrace': None
        }
    else:
        return process_article_with_llm(row)

def process_data_async(task_id: str, *args, **kwargs):
    """
    Fő aszinkron adatfeldolgozó függvény.
    Ez fut a háttérben RQ worker-ben.
    
    Args:
        task_id: A feladat azonosítója
        *args, **kwargs: RQ által átadott extra paraméterek (figyelmen kívül hagyjuk)
    """
    # TaskManager Redis-só inicializálása (worker környezetben nincs SocketIO)
    task_manager = TaskManager(socketio=None)
    
    try:
        # Cache kapcsolat tesztelése
        print("🔍 Cache rendszer ellenőrzése...", flush=True)
        cache_ok = test_cache_connection()
        if cache_ok:
            cache_stats = get_cache_stats()
            print(f"💾 Cache állapot: {cache_stats['cached_items']} tárolt elem, {cache_stats['memory_used_mb']} MB", flush=True)
        
        # Connection pool inicializálás
        print("🚄 HTTP Connection Pool inicializálása...", flush=True)
        pool_stats = get_connection_pool_stats()
        if pool_stats.get('active'):
            print(f"✅ Connection pool aktív: limit={pool_stats.get('limit', 'N/A')}, per_host={pool_stats.get('limit_per_host', 'N/A')}", flush=True)
        
        # Inkrementális feldolgozás inicializálása
        print("🔄 Inkrementális feldolgozás ellenőrzése...", flush=True)
        incremental = get_incremental_processor()
        inc_stats = incremental.get_stats()
        if inc_stats['last_processing_date']:
            print(f"📅 Utolsó feldolgozás: {inc_stats['last_processing_date']}", flush=True)
            print(f"📊 Tárolt cikkek: {inc_stats['total_articles_tracked']}", flush=True)
        else:
            print("🆕 Első feldolgozás - minden cikk feldolgozásra kerül", flush=True)
        
        # ML Worker Filter tréning (ha van elég adat)
        # TESZT MÓDBAN KIKAPCSOLVA - ne használja a régi 10k adatokat
        if not TEST_MODE:
            print("🎯 ML Worker Filter inicializálása...", flush=True)
            ml_trained = train_ml_filter_from_llm_log()
            if ml_trained:
                ml_stats = get_ml_filter().get_stats()
                print(f"✅ ML filter aktív: {ml_stats['relevant_samples']} releváns, {ml_stats['irrelevant_samples']} irreleváns minta", flush=True)
            else:
                print("⚠️ ML filter inaktív (nincs elég tréningadat)", flush=True)
        else:
            print("🧪 TESZT MÓD: ML Worker Filter kikapcsolva (ne használja a régi adatokat)", flush=True)
        
        
        task_manager.update_progress(task_id, 0.0, "Feladat indítása...")
        task_manager.set_status(task_id, "running", "Modell ellenőrzése...")
        
        # Modell pull (ha még nincs letöltve)
        try:
            # Ellenőrizzük, hogy a modell már létezik-e
            available_models = ollama.list()
            model_exists = any(MODEL_NAME in model.get('name', '') for model in available_models.get('models', []))
            
            if not model_exists:
                print(f"📥 Modell letöltése: {MODEL_NAME}", flush=True)
                ollama.pull(MODEL_NAME)
                print(f"✅ Modell letöltve: {MODEL_NAME}", flush=True)
            else:
                print(f"✅ Modell már elérhető: {MODEL_NAME}", flush=True)
        except Exception as e:
            # Ha nincs internet vagy már letöltve van, folytassuk
            print(f"⚠️  Modell ellenőrzési hiba (folytatás): {e}", flush=True)
        
        task_manager.update_progress(task_id, 0.0, "Adatok betöltése...")

        # Adatok betöltése és validálása
        if not os.path.exists(INPUT_FILE):
            raise FileNotFoundError(f"Input fájl nem található: {INPUT_FILE}")
        
        # 🔍 Parquet fájl elemzése streaming módban
        print("📊 Parquet fájl elemzése...", flush=True)
        file_info = estimate_parquet_memory(INPUT_FILE)
        print(f"   Fájl méret: {file_info['file_size_mb']} MB", flush=True)
        print(f"   Sorok száma: {file_info['total_rows']}", flush=True)
        print(f"   Becsült memória: {file_info['estimated_memory_mb']} MB", flush=True)
        print(f"   Ajánlott chunk méret: {file_info['recommended_chunk_size']}", flush=True)
        
        # Már feldolgozott elemek betöltése
        existing_processed = load_existing_results()
        existing_ids = set(existing_processed.keys())
        
        # 💾 Streaming unique articles - chunked processing
        print("🔄 Unique cikkek betöltése streaming módban...", flush=True)
        all_unique_articles = get_unique_articles_streaming(
            INPUT_FILE,
            article_id_column='article_id',
            chunk_size=file_info['recommended_chunk_size'],
            exclude_ids=set()  # Ne szűrjük ki semmit - inkrementális szűrés később
        )
        
        # 🔄 Inkrementális szűrés: csak új/módosult cikkek
        print("🔍 Inkrementális szűrés alkalmazása...", flush=True)
        unique_articles, new_checksums = incremental.filter_new_and_changed(
            all_unique_articles,
            timestamp_column='delivery_day',
            force_reprocess=False  # True-ra állítva minden cikket újrafeldolgoz
        )
        
        # Validáció egy kis mintán (első 100 sor)
        if len(unique_articles) > 0:
            sample_df = unique_articles.head(100)
            validate_dataframe_schema(sample_df)
        
        total_articles = len(all_unique_articles)  # Összes unique cikk
        articles_to_process = unique_articles  # Csak új/módosult
        
        # 🧪 TESZT MÓD: Csak első N hirdetést feldolgozni
        if TEST_MODE:
            print(f"🧪 TESZT MÓD AKTÍV: Csak első {TEST_LIMIT} hirdetést dolgozunk fel", flush=True)
            articles_to_process = articles_to_process.head(TEST_LIMIT)
        
        total_to_process = len(articles_to_process)
        already_processed = len(existing_processed)
        
        # Kezdeti progress: már feldolgozott / összes
        if total_articles > 0:
            initial_progress = (already_processed / total_articles) * 100
            task_manager.update_progress(
                task_id, initial_progress, 
                f"Betöltve: {already_processed}/{total_articles} már kész, {total_to_process} feldolgozandó",
                processed_items=already_processed,
                relevant_found=0,
                irrelevant_found=0,
                total_items=total_articles  # Összes elem beállítása!
            )
        else:
            task_manager.update_progress(
                task_id, 0.0, "Nincs feldolgozandó adat",
                total_items=0
            )
        
        if len(articles_to_process) == 0:
            task_manager.update_progress(task_id, 100.0, "Minden hirdetés már feldolgozott")
            task_manager.mark_completed(task_id, "Nincsenek új hirdetések feldolgozásra")
            return
        
        print(f"📊 KÉTFÁZISÚ FELDOLGOZÁS KEZDÉS:", flush=True)
        print(f"   Feldolgozandó cikkek: {total_to_process}", flush=True)
        print(f"   Már kész: {already_processed}", flush=True)
        
        # ============ 1. FÁZIS: WORKER ELŐSZŰRÉS (GYORS, SZEKVENCIÁLIS) ============
        print(f"🔍 1. FÁZIS: Worker előszűrés kezdése...", flush=True)
        
        worker_results = []
        articles_for_llm = []
        worker_filtered_count = 0
        worker_relevant_count = 0
        
        for i, (_, article) in enumerate(articles_to_process.iterrows()):
            worker_result = worker_filter_article(article)
            
            if worker_result['needs_llm']:
                # LLM-re van szükség
                articles_for_llm.append(article)
            else:
                # Worker eldöntötte
                if worker_result['relevant']:
                    worker_relevant_count += 1
                else:
                    worker_filtered_count += 1
                
                # Eredmény tárolása
                final_result = {
                    'article_id': worker_result['article_id'],
                    'relevant': worker_result['relevant'],
                    'reason': worker_result['reason'],
                    'description': article.get('description', ''),
                    'filtered_by': 'worker',
                    'floor': None, 'street': None, 'building_type': None,
                    'property_category': None, 'has_terrace': None
                }
                worker_results.append(final_result)
            
            # Progress update statisztikákkal
            if i % 10 == 0 or i == total_to_process - 1:  # Minden 10. elemnél update
                phase1_progress = ((i + 1) / total_to_process) * 50.0  # 1. fázis 0-50%
                current_processed = already_processed + len(worker_results)
                print(f"📊 Worker fázis frissítés: {phase1_progress:.1f}% - Worker {i+1}/{total_to_process} | Releváns: {worker_relevant_count}, Irreleváns: {worker_filtered_count}", flush=True)
                task_manager.update_progress(
                    task_id, phase1_progress, 
                    f"1. fázis - Worker előszűrés: {i+1}/{total_to_process}",
                    processed_items=current_processed,
                    relevant_found=worker_relevant_count,
                    irrelevant_found=worker_filtered_count,
                    total_items=total_articles
                )
        
        print(f"✅ 1. FÁZIS KÉSZ:", flush=True)
        print(f"   Worker által szűrt (irreleváns): {worker_filtered_count}", flush=True)
        print(f"   LLM elemzésre vár: {len(articles_for_llm)}", flush=True)
        
        # ============ 2. FÁZIS: LLM FELDOLGOZÁS BATCH-EKBEN (LASSÚ, PÁRHUZAMOS) ============
        print(f"🚀 2. FÁZIS: LLM elemzés kezdése ({len(articles_for_llm)} cikk, egyenként)...", flush=True)
        
        llm_results = []
        llm_processed_count = 0
        llm_relevant_count = 0
        
        if len(articles_for_llm) > 0:
            # BATCH PROCESSING KIKAPCSOLVA - egyenként dolgozzuk fel
            # A batch processing keveri össze a cikkeket (confusion)
            for article in articles_for_llm:
                individual_result = process_article_with_llm(article)
                llm_results.append(individual_result)
                llm_processed_count += 1
                if individual_result['relevant']:
                    llm_relevant_count += 1
            
            print(f"   Egyenként feldolgozva: {llm_processed_count} cikk", flush=True)
        
        # Eredmények egyesítése
        all_results = worker_results + llm_results
        
        # Végső statisztikák
        final_relevant_count = sum(1 for r in all_results if r['relevant'])
        final_irrelevant_count = len(all_results) - final_relevant_count
        final_processed_count = already_processed + len(all_results)
        
        # Eredmények mentése
        save_results(all_results)
        
        # 🔄 Inkrementális metadata frissítése
        print("📝 Inkrementális metadata frissítése...", flush=True)
        incremental.update_metadata(new_checksums, len(all_results))
        
        print(f"✅ 2. FÁZIS KÉSZ:", flush=True)
        print(f"   LLM által feldolgozott: {llm_processed_count}", flush=True)
        
        # Részletes statisztikák kiírása
        print(f"📊 VÉGSŐ STATISZTIKÁK:", flush=True)
        print(f"   Összes feldolgozott: {len(all_results)}", flush=True)
        print(f"   Releváns: {final_relevant_count}", flush=True)
        print(f"   Irreleváns: {final_irrelevant_count}", flush=True)
        print(f"   Worker által szűrt: {worker_filtered_count}", flush=True)
        print(f"   LLM által elemzett: {llm_processed_count}", flush=True)
        if len(all_results) > 0:
            print(f"   LLM hatékonyság: {llm_processed_count}/{len(all_results)} ({100*llm_processed_count/len(all_results):.1f}%)", flush=True)
        
        # Cache statisztikák a feldolgozás végén
        final_cache_stats = get_cache_stats()
        print(f"💾 CACHE STATISZTIKÁK:", flush=True)
        print(f"   Tárolt elemek: {final_cache_stats['cached_items']}", flush=True)
        print(f"   Memória használat: {final_cache_stats['memory_used_mb']} MB", flush=True)
        print(f"   TTL: {final_cache_stats['ttl_hours']} óra", flush=True)
        
        # Végső progress 100%-kal és statisztikákkal
        task_manager.update_progress(
            task_id, 100.0, 
            "Feldolgozás befejezve!",
            processed_items=final_processed_count,
            relevant_found=final_relevant_count,
            irrelevant_found=final_irrelevant_count,
            total_items=total_articles
        )
        task_manager.mark_completed(
            task_id, 
            f"✅ Kétfázisú feldolgozás kész! Worker szűrt: {worker_filtered_count}, LLM elemzett: {llm_processed_count}, Releváns: {final_relevant_count}"
        )
        
    except Exception as e:
        task_manager.mark_failed(task_id, str(e))
        raise

def load_existing_results() -> Dict[str, Dict]:
    """Korábban feldolgozott eredmények betöltése."""
    existing = {}
    
    # Releváns eredmények
    if os.path.exists(OUTPUT_FILE):
        relevant_df = pd.read_parquet(OUTPUT_FILE)
        for _, row in relevant_df.iterrows():
            existing[row['article_id']] = {'relevant': True, 'data': row.to_dict()}
    
    # Irreleváns eredmények  
    if os.path.exists(IRRELEVANT_OUTPUT_FILE):
        irrelevant_df = pd.read_parquet(IRRELEVANT_OUTPUT_FILE)
        for _, row in irrelevant_df.iterrows():
            existing[row['article_id']] = {'relevant': False, 'data': row.to_dict()}
    
    return existing

def save_results(results: List[Dict], input_file_path: str = INPUT_FILE):
    """
    Feldolgozási eredmények mentése + Human feedback CSV.
    Streaming módban dolgozik - nem tölti be a teljes eredeti DataFrame-et.
    """
    print(f"💾 save_results kezdése - {len(results)} eredmény feldolgozása", flush=True)
    
    # Releváns és irreleváns eredmények szétválasztása
    relevant_results = [r for r in results if r['relevant']]
    irrelevant_results = [r for r in results if not r['relevant']]
    
    # 🔄 Streaming: csak a feldolgozott article_id-kat keressük meg
    processed_ids = set(r['article_id'] for r in results)
    
    print(f"💾 Eredmények mentése streaming módban ({len(processed_ids)} cikk)...", flush=True)
    
    # Streaming olvasás - csak a releváns sorokat gyűjtjük
    relevant_rows = []
    irrelevant_rows = []
    
    reader = ParquetStreamReader(input_file_path, chunk_size=50000)
    for chunk in reader.iter_batches_pyarrow(batch_size=50000):
        # Szűrés: csak a feldolgozott cikkek
        processed_chunk = chunk[chunk['article_id'].isin(processed_ids)]
        
        if len(processed_chunk) > 0:
            # Releváns és irreleváns sorok szétválasztása
            for _, row in processed_chunk.iterrows():
                article_id = row['article_id']
                
                # Megkeressük a result-ot
                matching_result = next((r for r in results if r['article_id'] == article_id), None)
                
                if matching_result:
                    # Extra mezők hozzáadása
                    row_dict = row.to_dict()
                    if matching_result['relevant']:
                        row_dict['reason'] = matching_result.get('reason', '')
                        row_dict['floor'] = matching_result.get('floor')
                        row_dict['street'] = matching_result.get('street')
                        row_dict['building_type'] = matching_result.get('building_type')
                        row_dict['property_category'] = matching_result.get('property_category')
                        row_dict['has_terrace'] = matching_result.get('has_terrace')
                        relevant_rows.append(row_dict)
                    else:
                        row_dict['reason_to_relevance'] = matching_result.get('reason', '')
                        irrelevant_rows.append(row_dict)
    
    # DataFrame-ek létrehozása és mentése
    if relevant_rows:
        relevant_df = pd.DataFrame(relevant_rows)
        
        # Append módban mentés (ha már létezik a fájl)
        if os.path.exists(OUTPUT_FILE):
            existing_relevant = pd.read_parquet(OUTPUT_FILE)
            relevant_df = pd.concat([existing_relevant, relevant_df], ignore_index=True)
            # Duplikátumok eltávolítása
            relevant_df = relevant_df.drop_duplicates(subset=['article_id'], keep='last')
        
        relevant_df.to_parquet(OUTPUT_FILE, index=False)
        print(f"✅ {len(relevant_rows)} releváns sor mentve", flush=True)
    
    if irrelevant_rows:
        irrelevant_df = pd.DataFrame(irrelevant_rows)
        
        # Append módban mentés
        if os.path.exists(IRRELEVANT_OUTPUT_FILE):
            existing_irrelevant = pd.read_parquet(IRRELEVANT_OUTPUT_FILE)
            irrelevant_df = pd.concat([existing_irrelevant, irrelevant_df], ignore_index=True)
            # Duplikátumok eltávolítása
            irrelevant_df = irrelevant_df.drop_duplicates(subset=['article_id'], keep='last')
        
        irrelevant_df.to_parquet(IRRELEVANT_OUTPUT_FILE, index=False)
        print(f"✅ {len(irrelevant_rows)} irreleváns sor mentve", flush=True)
    
    # Human feedback CSV létrehozása
    try:
        print(f"📝 Human feedback CSV készítése - {len(results)} cikk feldolgozása...", flush=True)
        feedback_data = []
        for result in results:
            if result is None:
                print(f"⚠️ None result found, skipping...", flush=True)
                continue
                
            article_id = result.get('article_id', 'unknown')
            description = result.get('description') or ''  # Handle None
            description = description[:500] if description else ''  # Első 500 karakter
            relevant = result.get('relevant', False)
            reason = result.get('reason', '')
            filtered_by = result.get('filtered_by', 'unknown')
            
            feedback_data.append({
                'article_id': article_id,
                'description_preview': description,
                'llm_relevant': relevant,
                'llm_reason': reason,
                'filtered_by': filtered_by,
                'human_feedback': ''  # Üres oszlop human feedback-hez
            })
        
        print(f"📝 {len(feedback_data)} feedback bejegyzés előkészítve", flush=True)
        
        # Human feedback XLSX mentése (szerkeszthető Excel formátum)
        feedback_df = pd.DataFrame(feedback_data)
        feedback_xlsx_path = '/workspace/human_feedback.xlsx'
        
        # Ha már létezik, hozzáfűzés
        if os.path.exists(feedback_xlsx_path):
            existing_df = pd.read_excel(feedback_xlsx_path, engine='openpyxl')
            # Duplikátum elkerülése: csak azok amelyek még nincsenek benne
            existing_ids = set(existing_df['article_id'].values)
            new_feedback = feedback_df[~feedback_df['article_id'].isin(existing_ids)]
            if len(new_feedback) > 0:
                combined_df = pd.concat([existing_df, new_feedback], ignore_index=True)
                combined_df.to_excel(feedback_xlsx_path, index=False, engine='openpyxl')
                print(f"📝 Human feedback XLSX frissítve: +{len(new_feedback)} új cikk (össz: {len(combined_df)})", flush=True)
            else:
                print(f"📝 Human feedback XLSX már naprakész (nincs új cikk)", flush=True)
        else:
            feedback_df.to_excel(feedback_xlsx_path, index=False, engine='openpyxl')
            print(f"📝 Human feedback XLSX létrehozva: {len(feedback_data)} cikk - {feedback_xlsx_path}", flush=True)
    
    except Exception as e:
        print(f"❌ HIBA a human feedback CSV létrehozásánál: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
    
    # Log fájl frissítése
    try:
        log_df = pd.DataFrame(results)
        log_df.to_csv(LOG_FILE, index=False)
        print(f"📊 LLM decisions log frissítve: {len(results)} bejegyzés", flush=True)
    except Exception as e:
        print(f"❌ HIBA a log fájl frissítésénél: {str(e)}", flush=True)