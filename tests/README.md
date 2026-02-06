# 🧪 Unit Tests

Ez a mappa tartalmazza a Budapest Ingatlan Elemző rendszer unit tesztjeit.

## Tesztelés Futtatása

### Összes teszt futtatása
```bash
# Python környezetben
python run_tests.py

# Vagy közvetlenül pytest-tel
pytest tests/ -v

# Docker-ben
docker exec thesis_project-app-1 python run_tests.py
```

### Specifikus teszt fájl futtatása
```bash
pytest tests/test_llm_cache.py -v
pytest tests/test_models.py -v
pytest tests/test_incremental_processing.py -v
pytest tests/test_task_manager.py -v
```

### Coverage riport generálása
```bash
pytest tests/ --cov=app --cov-report=html
# Riport: htmlcov/index.html
```

## Teszt Struktúra

```
tests/
├── __init__.py
├── conftest.py                          # Shared fixtures
├── test_llm_cache.py                    # Cache tesztek (Redis)
├── test_models.py                       # Pydantic validáció tesztek
├── test_incremental_processing.py       # Hash-based change detection
└── test_task_manager.py                 # Progress tracking tesztek
```

## Fixtures (conftest.py)

### `mock_redis`
Mock Redis kapcsolat minden teszthez.

### `sample_article_data`
Minta hirdetés adat teszteléshez.

### `sample_llm_response`
Minta LLM válasz strukturált formátumban.

## Teszt Kategóriák

### Unit Tesztek
- **test_llm_cache.py**: SHA256 cache kezelés, TTL, hit/miss rate
- **test_models.py**: Pydantic séma validáció, type checking
- **test_incremental_processing.py**: Hash generation, change detection
- **test_task_manager.py**: Progress tracking, ETA számítás

### Marker Használat
```bash
# Csak unit tesztek
pytest -m unit

# Slow tesztek kihagyása
pytest -m "not slow"
```

## CI/CD Integráció

Tesztek automatikus futtatása GitHub Actions-ban vagy helyi pre-commit hook-kal:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest tests/ -v
```

## Előfeltételek

A tesztek futtatásához szükséges:
- Python 3.10+
- pytest 7.4+
- Mock Redis (automatikusan)
- Projekt dependencies (`requirements.txt`)

## Trouble shooting

### Import Error
Ha import hibát kapsz:
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)/app"
pytest tests/
```

### Redis Connection Error
A tesztek **nem igényelnek** futó Redis szervert, mert mock-olt Redis-t használnak.

## Újabb Tesztek Hozzáadása

Új teszt fájl létrehozása:
```python
# tests/test_new_module.py
import pytest

class TestNewFeature:
    def test_something(self, mock_redis):
        # Test implementation
        assert True
```

Futtasd az új tesztet:
```bash
pytest tests/test_new_module.py -v
```
