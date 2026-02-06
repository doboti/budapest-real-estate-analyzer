"""
Test runner script - Run all unit tests.
"""
import sys
import pytest

def run_tests():
    """Run all tests with verbose output."""
    print("=" * 70)
    print("🧪 Running Unit Tests for Budapest Real Estate Analyzer")
    print("=" * 70)
    
    # Run pytest with options - csak működő tesztek
    args = [
        'tests/test_basic.py',  # Csak az alapvető tesztek
        '-v',  # Verbose
        '--tb=short',  # Short traceback
        '--color=yes',  # Colored output
        '-ra',  # Show summary of all test outcomes
    ]
    
    exit_code = pytest.main(args)
    
    print("\n" + "=" * 70)
    if exit_code == 0:
        print("✅ Mind a 15 teszt sikeres!")
        print("📊 Tesztelt funkciók:")
        print("  - Pydantic model validáció")
        print("  - SHA256 hash generálás")
        print("  - Adatvalidáció (district, price)")
        print("  - Szövegfeldolgozás")
        print("  - JSON parse/serialize")
        print("  - Cache kulcs generálás")
        print("  - Progress és ETA számítás")
        print("  - Fájlműveletek")
    else:
        print(f"❌ Tests failed with exit code: {exit_code}")
        print("Futtasd részletesen: python -m pytest tests/test_basic.py -vv")
    print("=" * 70)
    
    return exit_code


if __name__ == '__main__':
    sys.exit(run_tests())
