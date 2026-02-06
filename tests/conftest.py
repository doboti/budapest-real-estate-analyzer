"""
Pytest configuration és shared fixtures.
"""
import pytest
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "app"))

# Mock Redis for tests
@pytest.fixture
def mock_redis(monkeypatch):
    """Mock Redis connection for testing."""
    class MockRedis:
        def __init__(self):
            self.store = {}
            self.ttl_store = {}
        
        def get(self, key):
            return self.store.get(key)
        
        def set(self, key, value, ex=None):
            self.store[key] = value
            if ex:
                self.ttl_store[key] = ex
            return True
        
        def delete(self, key):
            self.store.pop(key, None)
            return 1
        
        def keys(self, pattern):
            if pattern == "*":
                return list(self.store.keys())
            return []
        
        def dbsize(self):
            return len(self.store)
        
        def info(self, section=None):
            return {"used_memory": len(str(self.store))}
        
        def ping(self):
            return True
    
    return MockRedis()


@pytest.fixture
def sample_article_data():
    """Sample article data for testing."""
    return {
        'article_id': 'TEST_001',
        'title': '2 szobás lakás Budapest V. kerületben',
        'description': 'Eladó egy 65 nm-es, 2 szobás lakás a belvárosban. 3. emelet, lift van.',
        'price': 45000000,
        'area': 65,
        'district': 'V. kerület',
        'date': '2026-01-30'
    }


@pytest.fixture
def sample_llm_response():
    """Sample LLM response for testing."""
    return {
        'relevant': True,
        'reason': 'Lakás típusú ingatlan, megfelelő információval',
        'floor': 3,
        'street': None,
        'building_type': 'tégla',
        'property_category': 'lakás',
        'has_terrace': False
    }
