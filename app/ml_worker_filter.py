"""
ML-alapú Worker Szűrés
======================

TF-IDF vectorization és cosine similarity alapú előszűrés.
Megtanul a meglévő LLM döntésekből és gyorsítja a worker szűrést.
"""

import os
import pandas as pd
import numpy as np
import pickle
import redis
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import Dict, Any, Optional, Tuple
import re

# Redis connection
REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)

# ML model cache keys
ML_MODEL_KEY = 'ml_worker_filter:model'
ML_VECTORIZER_KEY = 'ml_worker_filter:vectorizer'
ML_TRAINING_DATA_KEY = 'ml_worker_filter:training_data'
ML_STATS_KEY = 'ml_worker_filter:stats'

# Thresholds
RELEVANT_THRESHOLD = 0.65  # Cosine similarity > 0.65 → valószínűleg releváns
IRRELEVANT_THRESHOLD = 0.35  # Cosine similarity < 0.35 → valószínűleg irreleváns

class MLWorkerFilter:
    """
    ML-alapú worker szűrő TF-IDF és cosine similarity-vel.
    """
    
    def __init__(self):
        self.vectorizer = None
        self.relevant_vectors = None
        self.irrelevant_vectors = None
        self.is_trained = False
        self.stats = {
            'relevant_samples': 0,
            'irrelevant_samples': 0,
            'total_predictions': 0,
            'confident_predictions': 0
        }
        
        # Próbáljuk betölteni a meglévő modellt
        self._load_from_redis()
    
    def _preprocess_text(self, text: str) -> str:
        """Szöveg előfeldolgozás TF-IDF-hez."""
        if not text:
            return ""
        
        # Lowercase
        text = text.lower()
        
        # Extra whitespace eltávolítása
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def train(self, training_data: pd.DataFrame) -> bool:
        """
        Modell tréning LLM döntések alapján.
        
        Args:
            training_data: DataFrame 'description' és 'relevant' oszlopokkal
            
        Returns:
            True ha sikeres, False egyébként
        """
        try:
            if training_data.empty or len(training_data) < 10:
                print("⚠️ ML Worker Filter: Nincs elég tréningadat (min 10 szükséges)", flush=True)
                return False
            
            # Szűrés: csak ahol van description és relevant
            training_data = training_data[
                training_data['description'].notna() & 
                training_data['relevant'].notna()
            ].copy()
            
            relevant_texts = training_data[training_data['relevant'] == True]['description'].tolist()
            irrelevant_texts = training_data[training_data['relevant'] == False]['description'].tolist()
            
            if len(relevant_texts) < 5 or len(irrelevant_texts) < 5:
                print(f"⚠️ ML Worker Filter: Nem elég példa (releváns: {len(relevant_texts)}, irreleváns: {len(irrelevant_texts)})", flush=True)
                return False
            
            # TF-IDF vectorizer létrehozása
            self.vectorizer = TfidfVectorizer(
                max_features=500,
                ngram_range=(1, 2),
                min_df=2,
                max_df=0.8,
                stop_words=None  # Magyar stopwordök nélkül
            )
            
            # Összes szöveg fittelése
            all_texts = relevant_texts + irrelevant_texts
            processed_texts = [self._preprocess_text(t) for t in all_texts]
            self.vectorizer.fit(processed_texts)
            
            # Releváns és irreleváns vektorok
            self.relevant_vectors = self.vectorizer.transform(
                [self._preprocess_text(t) for t in relevant_texts]
            )
            self.irrelevant_vectors = self.vectorizer.transform(
                [self._preprocess_text(t) for t in irrelevant_texts]
            )
            
            self.is_trained = True
            self.stats['relevant_samples'] = len(relevant_texts)
            self.stats['irrelevant_samples'] = len(irrelevant_texts)
            
            # Mentés Redis-be
            self._save_to_redis()
            
            print(f"✅ ML Worker Filter betanítva:", flush=True)
            print(f"   Releváns minták: {len(relevant_texts)}", flush=True)
            print(f"   Irreleváns minták: {len(irrelevant_texts)}", flush=True)
            print(f"   TF-IDF features: {len(self.vectorizer.get_feature_names_out())}", flush=True)
            
            return True
            
        except Exception as e:
            print(f"❌ ML Worker Filter tréning hiba: {e}", flush=True)
            return False
    
    def predict(self, description: str) -> Tuple[Optional[bool], float, str]:
        """
        Predikció egyedi leíráshoz.
        
        Args:
            description: Az ingatlanhirdetés leírása
            
        Returns:
            (relevant/None, confidence, reason)
            - relevant: True/False/None (None = bizonytalan)
            - confidence: 0.0-1.0 skála
            - reason: Indoklás string
        """
        if not self.is_trained:
            return None, 0.0, "ML modell nincs betanítva"
        
        try:
            # Szöveg vektorizálása
            processed = self._preprocess_text(description)
            if not processed:
                return None, 0.0, "Üres leírás"
            
            vector = self.vectorizer.transform([processed])
            
            # Cosine similarity mindkét kategóriával
            relevant_sim = cosine_similarity(vector, self.relevant_vectors).max()
            irrelevant_sim = cosine_similarity(vector, self.irrelevant_vectors).max()
            
            # Döntési logika
            self.stats['total_predictions'] += 1
            
            if relevant_sim > RELEVANT_THRESHOLD and relevant_sim > irrelevant_sim:
                self.stats['confident_predictions'] += 1
                confidence = relevant_sim
                return True, confidence, f"ML: Releváns (sim={relevant_sim:.2f})"
            
            elif irrelevant_sim > IRRELEVANT_THRESHOLD and irrelevant_sim > relevant_sim:
                self.stats['confident_predictions'] += 1
                confidence = irrelevant_sim
                return False, confidence, f"ML: Irreleváns (sim={irrelevant_sim:.2f})"
            
            else:
                # Bizonytalan eset → LLM-re bízzuk
                confidence = max(relevant_sim, irrelevant_sim)
                return None, confidence, f"ML: Bizonytalan (rel={relevant_sim:.2f}, irr={irrelevant_sim:.2f})"
                
        except Exception as e:
            print(f"❌ ML predikció hiba: {e}", flush=True)
            return None, 0.0, f"ML hiba: {str(e)}"
    
    def _save_to_redis(self):
        """Modell mentése Redis-be."""
        try:
            if not self.is_trained:
                return
            
            # Vectorizer mentése
            vectorizer_bytes = pickle.dumps(self.vectorizer)
            redis_client.set(ML_VECTORIZER_KEY, vectorizer_bytes)
            
            # Vektorok mentése
            relevant_bytes = pickle.dumps(self.relevant_vectors)
            irrelevant_bytes = pickle.dumps(self.irrelevant_vectors)
            redis_client.set(f"{ML_MODEL_KEY}:relevant", relevant_bytes)
            redis_client.set(f"{ML_MODEL_KEY}:irrelevant", irrelevant_bytes)
            
            # Statisztikák mentése
            import json
            redis_client.set(ML_STATS_KEY, json.dumps(self.stats))
            
            print("💾 ML modell mentve Redis-be", flush=True)
            
        except Exception as e:
            print(f"❌ ML modell mentés hiba: {e}", flush=True)
    
    def _load_from_redis(self):
        """Modell betöltése Redis-ből."""
        try:
            vectorizer_bytes = redis_client.get(ML_VECTORIZER_KEY)
            if not vectorizer_bytes:
                return
            
            self.vectorizer = pickle.loads(vectorizer_bytes)
            
            relevant_bytes = redis_client.get(f"{ML_MODEL_KEY}:relevant")
            irrelevant_bytes = redis_client.get(f"{ML_MODEL_KEY}:irrelevant")
            
            if relevant_bytes and irrelevant_bytes:
                self.relevant_vectors = pickle.loads(relevant_bytes)
                self.irrelevant_vectors = pickle.loads(irrelevant_bytes)
                self.is_trained = True
                
                # Statisztikák betöltése
                import json
                stats_json = redis_client.get(ML_STATS_KEY)
                if stats_json:
                    self.stats = json.loads(stats_json)
                
                print("✅ ML modell betöltve Redis-ből", flush=True)
                print(f"   Releváns minták: {self.stats['relevant_samples']}", flush=True)
                print(f"   Irreleváns minták: {self.stats['irrelevant_samples']}", flush=True)
                
        except Exception as e:
            print(f"⚠️ ML modell betöltés hiba: {e}", flush=True)
            self.is_trained = False
    
    def get_stats(self) -> Dict[str, Any]:
        """Modell statisztikák lekérdezése."""
        stats = self.stats.copy()
        stats['is_trained'] = self.is_trained
        
        if self.stats['total_predictions'] > 0:
            stats['confidence_rate'] = self.stats['confident_predictions'] / self.stats['total_predictions']
        else:
            stats['confidence_rate'] = 0.0
        
        return stats


# Singleton instance
_ml_filter_instance: Optional[MLWorkerFilter] = None

def get_ml_filter() -> MLWorkerFilter:
    """Singleton ML filter instance."""
    global _ml_filter_instance
    if _ml_filter_instance is None:
        _ml_filter_instance = MLWorkerFilter()
    return _ml_filter_instance

def train_ml_filter_from_llm_log():
    """
    ML modell tréning a meglévő LLM döntések logja alapján.
    Automatikusan hívódik a feldolgozás elején.
    """
    try:
        log_file = '/workspace/llm_decisions_log.csv'
        
        if not os.path.exists(log_file):
            print("⚠️ LLM log fájl nem található, ML tréning kihagyva", flush=True)
            return False
        
        # LLM log betöltése
        df = pd.read_csv(log_file)
        
        if df.empty or len(df) < 10:
            print("⚠️ Nincs elég LLM döntés a tréninghez (min 10)", flush=True)
            return False
        
        # ML filter tréning
        ml_filter = get_ml_filter()
        success = ml_filter.train(df)
        
        return success
        
    except Exception as e:
        print(f"❌ ML tréning hiba: {e}", flush=True)
        return False
