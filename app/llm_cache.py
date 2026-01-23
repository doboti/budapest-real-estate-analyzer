"""
Intelligens LLM cache rendszer Redis alapú tárolással.
Hasonló leírások eredményeinek gyors visszakeresése hash alapján.
"""

import hashlib
import json
import redis
from typing import Optional, Dict, Any
from datetime import timedelta

# Redis kapcsolat
redis_client = redis.Redis(
    host='redis',
    port=6379,
    db=0,
    decode_responses=True
)

# Cache beállítások
CACHE_TTL_HOURS = 48  # 48 órás lejárat
CACHE_PREFIX = "llm_cache:"

def generate_cache_key(description: str) -> str:
    """
    SHA256 hash generálása a leírásból cache key-ként.
    
    Args:
        description: Az ingatlanhirdetés leírása
        
    Returns:
        Cache key (SHA256 hash)
    """
    # Normalizálás: kis betűk, trim, whitespace cleanup
    normalized = description.strip().lower()
    normalized = ' '.join(normalized.split())  # Többszörös whitespace eltávolítása
    
    # SHA256 hash
    hash_object = hashlib.sha256(normalized.encode('utf-8'))
    hash_hex = hash_object.hexdigest()
    
    return f"{CACHE_PREFIX}{hash_hex}"

def get_cached_result(description: str) -> Optional[Dict[str, Any]]:
    """
    Cache-elt eredmény lekérése.
    
    Args:
        description: Az ingatlanhirdetés leírása
        
    Returns:
        Cache-elt eredmény dict vagy None ha nincs cache
    """
    try:
        cache_key = generate_cache_key(description)
        cached_json = redis_client.get(cache_key)
        
        if cached_json:
            result = json.loads(cached_json)
            print(f"✅ Cache HIT: {cache_key[:20]}...", flush=True)
            return result
        
        print(f"❌ Cache MISS: {cache_key[:20]}...", flush=True)
        return None
        
    except Exception as e:
        print(f"⚠️ Cache READ error: {e}", flush=True)
        return None

def set_cached_result(description: str, result: Dict[str, Any]) -> bool:
    """
    Eredmény mentése cache-be.
    
    Args:
        description: Az ingatlanhirdetés leírása
        result: Az LLM által visszaadott eredmény dict
        
    Returns:
        True ha sikeres a mentés, False különben
    """
    try:
        cache_key = generate_cache_key(description)
        result_json = json.dumps(result, ensure_ascii=False)
        
        # TTL beállítása (48 óra)
        ttl = timedelta(hours=CACHE_TTL_HOURS)
        redis_client.setex(cache_key, ttl, result_json)
        
        print(f"💾 Cache SAVE: {cache_key[:20]}... (TTL: {CACHE_TTL_HOURS}h)", flush=True)
        return True
        
    except Exception as e:
        print(f"⚠️ Cache WRITE error: {e}", flush=True)
        return False

def get_cache_stats() -> Dict[str, Any]:
    """
    Cache statisztikák lekérése.
    
    Returns:
        Dict cache metrikákkal (keys count, memory usage, hit rate)
    """
    try:
        # Cache kulcsok száma
        keys = redis_client.keys(f"{CACHE_PREFIX}*")
        keys_count = len(keys)
        
        # Redis info
        info = redis_client.info('memory')
        memory_used_mb = info.get('used_memory', 0) / (1024 * 1024)
        
        return {
            'cached_items': keys_count,
            'memory_used_mb': round(memory_used_mb, 2),
            'cache_prefix': CACHE_PREFIX,
            'ttl_hours': CACHE_TTL_HOURS
        }
        
    except Exception as e:
        print(f"⚠️ Cache STATS error: {e}", flush=True)
        return {
            'cached_items': 0,
            'memory_used_mb': 0,
            'error': str(e)
        }

def clear_cache() -> int:
    """
    Cache teljes törlése (csak LLM cache, nem érinti a task management-et).
    
    Returns:
        Törölt kulcsok száma
    """
    try:
        keys = redis_client.keys(f"{CACHE_PREFIX}*")
        if keys:
            deleted = redis_client.delete(*keys)
            print(f"🗑️ Cache CLEARED: {deleted} kulcs törölve", flush=True)
            return deleted
        return 0
        
    except Exception as e:
        print(f"⚠️ Cache CLEAR error: {e}", flush=True)
        return 0

def test_cache_connection() -> bool:
    """
    Redis cache kapcsolat tesztelése.
    
    Returns:
        True ha a kapcsolat működik
    """
    try:
        redis_client.ping()
        print("✅ Cache connection OK", flush=True)
        return True
    except Exception as e:
        print(f"❌ Cache connection FAILED: {e}", flush=True)
        return False
