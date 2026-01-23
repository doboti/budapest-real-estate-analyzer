"""
Pydantic modellek adatvalidációhoz és séma kezeléshez.
Ez biztosítja az LLM kimenetek és adatbevitelek strukturált validálását.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal, Union
import pandas as pd

class LLMResponse(BaseModel):
    """LLM válasz validációs modell."""
    relevant: bool = Field(..., description="Az ingatlan releváns-e")
    reason: str = Field(..., description="A döntés indoklása") 
    floor: Optional[int] = Field(None, description="Emelet száma")
    street: Optional[str] = Field(None, description="Utca neve")
    building_type: Optional[Literal["tegla", "panel", "egyeb"]] = Field(None, description="Építési mód")
    property_category: Optional[Literal["lakas", "haz"]] = Field(None, description="Ingatlan kategória")
    has_terrace: Optional[bool] = Field(None, description="Van-e terasz/erkély")
    
    @validator('floor')
    def validate_floor(cls, v):
        if v is not None and (v < -5 or v > 50):
            raise ValueError('Az emelet értéke -5 és 50 között kell legyen')
        return v
    
    @validator('street')
    def validate_street(cls, v):
        if v is not None and len(v.strip()) == 0:
            return None
        return v

class PropertyInput(BaseModel):
    """Ingatlan adatok bemeneti validációs modell."""
    article_id: str = Field(..., description="Hirdetés azonosító")
    description: Optional[str] = Field(None, description="Hirdetés leírása")
    title: Optional[str] = Field(None, description="Hirdetés címe")
    price_huf: Optional[float] = Field(None, description="Ár forintban")
    area_sqm: Optional[float] = Field(None, description="Terület m2-ben")
    district: Optional[str] = Field(None, description="Kerület")
    delivery_day: Optional[str] = Field(None, description="Hirdetés dátuma")
    
    @validator('description', pre=True)
    def validate_description(cls, v):
        if v is None or pd.isna(v):
            return ""  # Üres string a None helyett
        return str(v)  # Konvertálás string-re
    
    @validator('delivery_day', pre=True)
    def validate_delivery_day(cls, v):
        if v is None or pd.isna(v):
            return None
        # Pandas Timestamp konverzió string-re
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
        return str(v)
    
    @validator('price_huf')
    def validate_price(cls, v):
        if v is not None and (v < 0 or v > 10_000_000_000):  # 10 milliárdig
            raise ValueError('Az ár 0 és 10 milliárd forint között kell legyen')
        return v
    
    @validator('area_sqm')
    def validate_area(cls, v):
        if v is not None and (v < 10 or v > 1000):
            raise ValueError('A terület 10 és 1000 m2 között kell legyen')
        return v

class TaskStatus(BaseModel):
    """Háttérfeladat státusz modell prediktív ETA tracking-gel."""
    task_id: str = Field(..., description="Feladat azonosító")
    status: Literal["pending", "running", "completed", "failed"] = Field(..., description="Feladat állapota")
    progress: float = Field(0.0, ge=0.0, le=100.0, description="Haladás százalékban")
    message: str = Field("", description="Státusz üzenet")
    total_items: Optional[int] = Field(None, description="Összes feldolgozandó elem")
    processed_items: int = Field(0, description="Feldolgozott elemek száma")
    relevant_found: int = Field(0, description="Releváns hirdetések száma")
    irrelevant_found: int = Field(0, description="Irreleváns hirdetések száma")
    
    # Prediktív ETA tracking mezők
    start_time: Optional[float] = Field(None, description="Feldolgozás kezdési időpontja (timestamp)")
    elapsed_seconds: Optional[float] = Field(None, description="Eltelt idő másodpercben")
    eta_seconds: Optional[float] = Field(None, description="Becsült hátralévő idő másodpercben")
    items_per_second: Optional[float] = Field(None, description="Feldolgozási sebesség (elem/sec)")
    estimated_total_seconds: Optional[float] = Field(None, description="Becsült teljes feldolgozási idő")
    
def validate_dataframe_schema(df: pd.DataFrame) -> bool:
    """Pandera-szerű validáció a bemeneti Parquet fájlokhoz."""
    required_columns = ['article_id', 'description']
    
    # Kötelező oszlopok ellenőrzése
    missing_cols = set(required_columns) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Hiányzó kötelező oszlopok: {missing_cols}")
    
    # Alapvető adattípus ellenőrzések
    if df['article_id'].isnull().any():
        raise ValueError("Az article_id oszlopban nem lehet üres érték")
    
    # Duplikátumok ellenőrzése - csak figyelmeztetés, nem hiba
    unique_count = len(df['article_id'].unique())
    total_count = len(df)
    if unique_count != total_count:
        print(f"ℹ️  Figyelem: {total_count - unique_count} duplikált article_id található. Ez normális raw adatoknál.")
    
    return True

def sanitize_llm_output(content: str) -> dict:
    """LLM kimenet sanitizálása és safe parsing."""
    import json
    import re
    
    # JSON objektum kinyerése a válaszból
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        return {"relevant": False, "reason": "Hibás LLM válasz formátum"}
    
    try:
        raw_data = json.loads(json_match.group(0))
        # Pydantic validáció
        validated = LLMResponse(**raw_data)
        return validated.dict()
    except json.JSONDecodeError:
        return {"relevant": False, "reason": "Hibás JSON formátum"}
    except Exception as e:
        return {"relevant": False, "reason": f"Validációs hiba: {str(e)}"}