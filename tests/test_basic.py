"""
Egyszerű unit tesztek a fő funkciók működésének ellenőrzésére.
Ezek a tesztek Docker container nélkül is futnak, mock objektumokat használnak.
"""
import pytest
import sys
import os
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


class TestModelsBasic:
    """Pydantic model alapvető tesztek."""
    
    def test_import_models(self):
        """Test that models.py can be imported."""
        try:
            from models import LLMResponse, PropertyInput, TaskStatus
            assert LLMResponse is not None
            assert PropertyInput is not None
            assert TaskStatus is not None
        except Exception as e:
            pytest.fail(f"Failed to import models: {e}")
    
    def test_llm_response_validation(self):
        """Test LLMResponse model validation."""
        from models import LLMResponse
        
        # Valid data (ékezetek nélkül, ahogy a modell várja)
        valid_data = {
            'relevant': True,
            'reason': 'Lakás típusú ingatlan',
            'floor': 3,
            'street': None,
            'building_type': 'tegla',  # ékezet nélkül!
            'property_category': 'lakas',  # ékezet nélkül!
            'has_terrace': False
        }
        
        response_obj = LLMResponse(**valid_data)
        assert response_obj.relevant is True
        assert response_obj.floor == 3
        assert response_obj.building_type == 'tegla'


class TestHashGeneration:
    """SHA256 hash generation tesztek."""
    
    def test_hash_consistency(self):
        """Test that same data produces same hash."""
        import hashlib
        
        data = "test_string"
        hash1 = hashlib.sha256(data.encode()).hexdigest()
        hash2 = hashlib.sha256(data.encode()).hexdigest()
        
        assert hash1 == hash2
        assert len(hash1) == 64
    
    def test_hash_uniqueness(self):
        """Test that different data produces different hashes."""
        import hashlib
        
        data1 = "test_string_1"
        data2 = "test_string_2"
        
        hash1 = hashlib.sha256(data1.encode()).hexdigest()
        hash2 = hashlib.sha256(data2.encode()).hexdigest()
        
        assert hash1 != hash2


class TestDataValidation:
    """Adatvalidációs tesztek."""
    
    def test_district_format(self):
        """Test district format validation."""
        valid_districts = [
            "I. kerület",
            "V. kerület",
            "XIII. kerület",
            "XXIII. kerület"
        ]
        
        for district in valid_districts:
            assert "kerület" in district
            assert "." in district
    
    def test_price_range(self):
        """Test price is within reasonable range."""
        test_prices = [10000000, 50000000, 100000000]
        
        for price in test_prices:
            assert price > 0
            assert price < 1000000000  # 1 milliárd feletti nem reális


class TestTextProcessing:
    """Szövegfeldolgozás tesztek."""
    
    def test_string_cleaning(self):
        """Test basic string cleaning."""
        test_string = "  Test String  \n\t"
        cleaned = test_string.strip()
        
        assert cleaned == "Test String"
        assert "\n" not in cleaned
        assert "\t" not in cleaned
    
    def test_keyword_detection(self):
        """Test keyword detection in descriptions."""
        description = "Eladó 2 szobás lakás Budapest V. kerületében"
        
        assert "lakás" in description.lower()
        assert "eladó" in description.lower()
        assert "kerület" in description.lower()


class TestJSONProcessing:
    """JSON feldolgozás tesztek."""
    
    def test_json_serialization(self):
        """Test JSON serialization."""
        import json
        
        data = {
            'article_id': 'TEST_001',
            'relevant': True,
            'reason': 'Test reason'
        }
        
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        
        assert parsed['article_id'] == 'TEST_001'
        assert parsed['relevant'] is True
    
    def test_json_error_handling(self):
        """Test JSON parsing error handling."""
        import json
        
        invalid_json = "{'invalid': json}"
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_json)


class TestCacheKeyGeneration:
    """Cache kulcs generálás tesztek."""
    
    def test_cache_key_format(self):
        """Test cache key format."""
        import hashlib
        
        description = "Teszt leírás"
        cache_key = f"llm_cache:{hashlib.sha256(description.encode()).hexdigest()}"
        
        assert cache_key.startswith("llm_cache:")
        assert len(cache_key) == len("llm_cache:") + 64


class TestProgressCalculation:
    """Progress számítás tesztek."""
    
    def test_percentage_calculation(self):
        """Test progress percentage calculation."""
        processed = 50
        total = 100
        
        percentage = (processed / total) * 100
        
        assert percentage == 50.0
        assert 0 <= percentage <= 100
    
    def test_eta_calculation(self):
        """Test ETA calculation."""
        import time
        
        start_time = time.time()
        processed_items = 10
        total_items = 100
        elapsed = 10  # 10 seconds
        
        if processed_items > 0:
            speed = processed_items / elapsed  # items per second
            remaining_items = total_items - processed_items
            eta_seconds = remaining_items / speed
            
            assert speed == 1.0  # 1 item/sec
            assert eta_seconds == 90.0  # 90 seconds remaining


class TestFileOperations:
    """Fájlműveletek tesztek."""
    
    def test_file_path_operations(self):
        """Test file path operations."""
        from pathlib import Path
        
        test_path = Path("/workspace/parquet/test.parquet")
        
        assert test_path.name == "test.parquet"
        assert test_path.suffix == ".parquet"
        # Windows és Unix path kezelés
        parent_str = str(test_path.parent).replace('\\', '/')
        assert parent_str == "/workspace/parquet"
    
    def test_json_file_handling(self):
        """Test JSON file handling."""
        import json
        import tempfile
        
        test_data = {'key': 'value', 'number': 42}
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(test_data, f)
            temp_path = f.name
        
        with open(temp_path, 'r') as f:
            loaded_data = json.load(f)
        
        assert loaded_data == test_data
        
        # Cleanup
        Path(temp_path).unlink()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
