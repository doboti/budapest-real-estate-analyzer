"""
Airflow-kompatibilis adatfeldolgozó függvények.
Ezek a függvények helyettesítik a régi RQ-alapú background_tasks.py-t.
"""

import pandas as pd
import asyncio
import aiohttp
from typing import List, Dict, Any
import sys
import os

# Projekt könyvtár hozzáadása
sys.path.insert(0, '/workspace/app')

from llm_cache import get_cached_result, set_cached_result
from models import sanitize_llm_output
import ollama

MODEL_NAME = os.getenv('LLM_MODEL', 'llama3.2:3b')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434')
LOG_FILE = '/workspace/llm_decisions_log.csv'


async def async_ollama_chat(session: aiohttp.ClientSession, prompt: str, model: str = MODEL_NAME) -> Dict[str, Any]:
    """Aszinkron LLM hívás"""
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
    except Exception as e:
        print(f"❌ LLM hívás hiba: {e}")
        return None


async def async_process_single_article(session: aiohttp.ClientSession, article: Dict) -> Dict:
    """Egyetlen cikk feldolgozása cache-eléssel"""
    description = str(article.get('description', ''))
    article_id = article.get('article_id', 'unknown')
    
    # Cache ellenőrzés
    cached = get_cached_result(description)
    if cached:
        print(f"💾 Cache hit: {article_id}")
        return {**article, **cached}
    
    # LLM hívás
    prompt = f"""
Elemezd ezt a budapesti ingatlanhirdetést:

Leírás: {description}

Releváns: BÁRMILYEN ingatlan Budapesten (lakás, ház, telek, garázs stb.)
Irreleváns: Tulajdoni hányad, bérleti jog, haszonélvezet, csere

JSON válasz:
{{"relevant": true/false, "reason": "indoklás"}}
"""
    
    response = await async_ollama_chat(session, prompt)
    if not response:
        return {**article, 'relevant': False, 'reason': 'LLM hiba'}
    
    # Parse eredmény
    try:
        content = response['message']['content']
        sanitized = sanitize_llm_output(content)
        import json
        result = json.loads(sanitized)
        
        # Cache mentés
        set_cached_result(description, result)
        
        return {**article, **result}
    except Exception as e:
        print(f"⚠️ Parse hiba {article_id}: {e}")
        return {**article, 'relevant': False, 'reason': 'Parse hiba'}


async def async_process_articles_batch(df: pd.DataFrame) -> List[Dict]:
    """
    Teljes adathalmaz feldolgozása batch-ekben.
    Airflow task számára optimalizált.
    """
    results = []
    
    async with aiohttp.ClientSession() as session:
        # Batch-ek létrehozása (50 cikk/batch párhuzamos feldolgozásra)
        batch_size = 50
        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i+batch_size]
            
            # Párhuzamos feldolgozás aszinkron módon
            tasks = [async_process_single_article(session, row) for _, row in batch.iterrows()]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            
            print(f"✅ Feldolgozva: {len(results)}/{len(df)} cikk")
    
    return results


def save_llm_decisions_to_log(results: List[Dict]):
    """LLM döntések mentése CSV-be (ML tréninghez)"""
    import csv
    
    with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['article_id', 'description', 'relevant', 'reason'])
        
        for result in results:
            writer.writerow({
                'article_id': result.get('article_id'),
                'description': result.get('description', ''),
                'relevant': result.get('relevant'),
                'reason': result.get('reason', '')
            })
    
    print(f"📝 {len(results)} LLM döntés mentve: {LOG_FILE}")
