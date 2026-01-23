"""
Optimalizált HTTP connection pooling az Ollama LLM hívásokhoz.
Persistent session pool connection reuse-zal és keep-alive támogatással.
"""

import aiohttp
from typing import Optional
import atexit


class OllamaConnectionPool:
    """
    Singleton connection pool az Ollama HTTP hívásokhoz.
    Újrahasználható aiohttp session persistent connections-szel.
    """
    
    _instance: Optional['OllamaConnectionPool'] = None
    _session: Optional[aiohttp.ClientSession] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Session csak akkor jön létre amikor először hívjuk
        # (lazy initialization az event loop problémák elkerülésére)
        pass
    
    def _create_session(self) -> aiohttp.ClientSession:
        """Belső session létrehozás (lazy initialization)."""
        # Optimalizált TCP connector beállítások
        connector = aiohttp.TCPConnector(
            limit=100,  # Max concurrent connections
            limit_per_host=30,  # Max connections per host (Ollama server)
            ttl_dns_cache=300,  # DNS cache TTL (5 perc)
            enable_cleanup_closed=True,  # Cleanup closed connections
            force_close=False,  # Keep-alive connections
            keepalive_timeout=60,  # Keep-alive timeout (60s)
        )
        
        # Timeout beállítások
        timeout = aiohttp.ClientTimeout(
            total=300,  # Total request timeout
            connect=10,  # Connection timeout
            sock_read=300,  # Socket read timeout
        )
        
        # Session létrehozása optimalizált beállításokkal
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            connector_owner=True,  # A session birtokolja a connector-t
            headers={
                'Connection': 'keep-alive',
                'Keep-Alive': 'timeout=60, max=100'
            }
        )
        
        return session
    
    def get_session(self) -> aiohttp.ClientSession:
        """
        Visszaadja az újrahasználható session-t.
        Lazy initialization - csak akkor hoz létre session-t amikor szükséges.
        
        Returns:
            Optimalizált aiohttp ClientSession
        """
        if self._session is None or self._session.closed:
            self._session = self._create_session()
            # Cleanup regisztrálása első létrehozáskor
            atexit.register(self._cleanup)
        return self._session
    
    async def close(self):
        """Session lezárása (cleanup)."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _cleanup(self):
        """Sync cleanup at exit."""
        if self._session and not self._session.closed:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
            except Exception:
                # Best effort cleanup
                pass
    
    def get_stats(self) -> dict:
        """
        Connection pool statisztikák lekérése.
        
        Returns:
            Dictionary a pool állapotával
        """
        if self._session is None or self._session.closed:
            return {
                'status': 'closed',
                'active': False
            }
        
        connector = self._session.connector
        if isinstance(connector, aiohttp.TCPConnector):
            return {
                'status': 'active',
                'active': True,
                'limit': connector.limit,
                'limit_per_host': connector.limit_per_host,
                'acquired_per_host': len(connector._acquired_per_host) if hasattr(connector, '_acquired_per_host') else 0,
                'keepalive_timeout': connector._keepalive_timeout,
            }
        
        return {
            'status': 'active',
            'active': True
        }


# Global singleton instance
_connection_pool = OllamaConnectionPool()


def get_ollama_session() -> aiohttp.ClientSession:
    """
    Helper függvény az optimalizált Ollama session lekérésére.
    
    Returns:
        Persistent aiohttp ClientSession connection pooling-gal
    """
    return _connection_pool.get_session()


def get_connection_pool_stats() -> dict:
    """
    Connection pool statisztikák lekérése.
    
    Returns:
        Dictionary a pool állapotával
    """
    return _connection_pool.get_stats()


async def close_connection_pool():
    """
    Connection pool lezárása (cleanup).
    Használd application shutdown-kor.
    """
    await _connection_pool.close()
