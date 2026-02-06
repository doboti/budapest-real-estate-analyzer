"""
Unit tests for llm_cache.py - Redis cache management.
"""
import pytest
import json
from unittest.mock import Mock, patch
from llm_cache import LLMCache, get_cache_stats


class TestLLMCache:
    """Test LLM Cache functionality."""
    
    def test_cache_initialization(self, mock_redis):
        """Test cache initializes with Redis connection."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            assert cache.redis is not None
            assert cache.default_ttl == 172800  # 48h
    
    def test_generate_cache_key(self, mock_redis):
        """Test SHA256 hash generation for cache keys."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            text = "Test apartment description"
            key = cache.generate_key(text)
            
            assert isinstance(key, str)
            assert len(key) == 64  # SHA256 produces 64 char hex
            
            # Same text should produce same key
            key2 = cache.generate_key(text)
            assert key == key2
    
    def test_cache_set_and_get(self, mock_redis, sample_llm_response):
        """Test caching LLM results."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            description = "Beautiful 2 bedroom apartment"
            
            # Set cache
            cache.set(description, sample_llm_response)
            
            # Get cache
            result = cache.get(description)
            assert result is not None
            assert result['relevant'] == True
            assert result['floor'] == 3
    
    def test_cache_miss(self, mock_redis):
        """Test cache miss returns None."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            result = cache.get("Non-existent description")
            assert result is None
    
    def test_cache_clear(self, mock_redis):
        """Test clearing all cache entries."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            
            # Add some entries
            cache.set("desc1", {"relevant": True})
            cache.set("desc2", {"relevant": False})
            
            # Clear cache
            deleted = cache.clear()
            assert deleted >= 0
            
            # Verify cleared
            assert cache.get("desc1") is None
            assert cache.get("desc2") is None
    
    def test_get_cache_stats(self, mock_redis):
        """Test cache statistics retrieval."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            cache.set("test", {"relevant": True})
            
            stats = cache.get_stats()
            assert 'cached_items' in stats
            assert 'memory_used_mb' in stats
            assert 'ttl_hours' in stats
            assert stats['ttl_hours'] == 48


class TestCacheValidation:
    """Test cache data validation."""
    
    def test_invalid_json_handling(self, mock_redis):
        """Test handling of corrupted cache data."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            
            # Manually insert invalid JSON
            key = cache.generate_key("test")
            mock_redis.set(key, "invalid json{")
            
            # Should return None on invalid JSON
            result = cache.get("test")
            assert result is None
    
    def test_cache_key_normalization(self, mock_redis):
        """Test text normalization for consistent keys."""
        with patch('llm_cache.redis.Redis', return_value=mock_redis):
            cache = LLMCache()
            
            text1 = "  Test   Description  "
            text2 = "Test Description"
            
            key1 = cache.generate_key(text1.strip())
            key2 = cache.generate_key(text2.strip())
            
            # After normalization, should be same
            assert key1 == key2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
