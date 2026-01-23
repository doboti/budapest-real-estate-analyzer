"""
Inkrementális adatfeldolgozás - csak új/módosult adatok feldolgozása.
Timestamp és hash-based change detection.
"""

import os
import json
import hashlib
import pandas as pd
from datetime import datetime
from typing import Dict, Set, Tuple, Optional
from pathlib import Path


class IncrementalProcessor:
    """
    Inkrementális feldolgozás kezelő osztály.
    Timestamp és checksum alapú változás detektálás.
    """
    
    def __init__(self, metadata_file: str = '/workspace/processing_metadata.json'):
        """
        Inicializálás.
        
        Args:
            metadata_file: Metadata fájl elérési útja (JSON)
        """
        self.metadata_file = metadata_file
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict:
        """Metadata betöltése fájlból (ha létezik)."""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Metadata betöltési hiba: {e}", flush=True)
                return self._default_metadata()
        return self._default_metadata()
    
    def _default_metadata(self) -> Dict:
        """Default metadata struktúra."""
        return {
            'last_processing_timestamp': None,
            'last_processing_date': None,
            'total_processed': 0,
            'article_checksums': {}  # {article_id: sha256_hash}
        }
    
    def _save_metadata(self):
        """Metadata mentése fájlba."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)
            print(f"💾 Metadata mentve: {self.metadata_file}", flush=True)
        except Exception as e:
            print(f"⚠️ Metadata mentési hiba: {e}", flush=True)
    
    def compute_article_hash(self, article_data: pd.Series) -> str:
        """
        Cikk hash számítása (checksum a változás detektáláshoz).
        
        Args:
            article_data: Article sor (pandas Series)
            
        Returns:
            SHA256 hash (hex string)
        """
        # Kulcs mezők a hash számításhoz
        key_fields = ['description', 'title', 'price_huf', 'area_sqm', 'district']
        
        # Értékek összefűzése
        data_str = ""
        for field in key_fields:
            value = article_data.get(field, '')
            if pd.notna(value):
                data_str += str(value)
        
        # SHA256 hash
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()
    
    def filter_new_and_changed(
        self, 
        df: pd.DataFrame,
        timestamp_column: str = 'delivery_day',
        force_reprocess: bool = False
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """
        Szűrés: csak új vagy módosult cikkek.
        
        Args:
            df: Input DataFrame (teljes adathalmaz)
            timestamp_column: Timestamp oszlop neve
            force_reprocess: Ha True, minden cikket újrafeldolgoz
            
        Returns:
            Tuple: (Szűrt DataFrame csak új/módosult cikkekkel, Új checksumok dict)
        """
        if force_reprocess:
            print("🔄 Force reprocess mode: minden cikk feldolgozásra kerül", flush=True)
            new_checksums = {}
            for _, row in df.iterrows():
                article_id = row['article_id']
                new_checksums[article_id] = self.compute_article_hash(row)
            return df, new_checksums
        
        last_timestamp = self.metadata.get('last_processing_timestamp')
        existing_checksums = self.metadata.get('article_checksums', {})
        
        print(f"📊 Inkrementális szűrés indítása...", flush=True)
        print(f"   Utolsó feldolgozás: {self.metadata.get('last_processing_date', 'Soha')}", flush=True)
        print(f"   Korábban feldolgozott cikkek: {len(existing_checksums)}", flush=True)
        
        new_articles = []
        changed_articles = []
        unchanged_articles = []
        new_checksums = {}
        
        for idx, row in df.iterrows():
            article_id = row['article_id']
            current_hash = self.compute_article_hash(row)
            new_checksums[article_id] = current_hash
            
            # 1. Új cikk (még nem volt feldolgozva)
            if article_id not in existing_checksums:
                new_articles.append(idx)
                continue
            
            # 2. Módosult cikk (hash változás)
            if existing_checksums[article_id] != current_hash:
                changed_articles.append(idx)
                continue
            
            # 3. Változatlan cikk
            unchanged_articles.append(idx)
        
        print(f"✅ Szűrési eredmény:", flush=True)
        print(f"   🆕 Új cikkek: {len(new_articles)}", flush=True)
        print(f"   🔄 Módosult cikkek: {len(changed_articles)}", flush=True)
        print(f"   ✓ Változatlan cikkek: {len(unchanged_articles)}", flush=True)
        
        # Csak az új és módosult cikkek DataFrame-je
        filtered_indices = new_articles + changed_articles
        filtered_df = df.loc[filtered_indices].copy() if filtered_indices else pd.DataFrame()
        
        return filtered_df, new_checksums
    
    def update_metadata(self, new_checksums: Dict[str, str], processed_count: int):
        """
        Metadata frissítése feldolgozás után.
        
        Args:
            new_checksums: Új cikk checksumok dictionary
            processed_count: Feldolgozott cikkek száma
        """
        current_time = datetime.now()
        
        # Checksumok frissítése (merge új + meglévő)
        self.metadata['article_checksums'].update(new_checksums)
        
        # Timestamp frissítése
        self.metadata['last_processing_timestamp'] = current_time.timestamp()
        self.metadata['last_processing_date'] = current_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Összesített statisztikák
        self.metadata['total_processed'] = len(self.metadata['article_checksums'])
        
        # Mentés
        self._save_metadata()
        
        print(f"📈 Metadata frissítve:", flush=True)
        print(f"   Feldolgozva most: {processed_count}", flush=True)
        print(f"   Összes cikk: {self.metadata['total_processed']}", flush=True)
    
    def get_stats(self) -> Dict:
        """
        Inkrementális feldolgozás statisztikák.
        
        Returns:
            Dictionary statisztikákkal
        """
        return {
            'last_processing_date': self.metadata.get('last_processing_date'),
            'total_articles_tracked': len(self.metadata.get('article_checksums', {})),
            'metadata_file': self.metadata_file,
            'metadata_exists': os.path.exists(self.metadata_file)
        }
    
    def reset_metadata(self):
        """Metadata törlése (teljes újrafeldolgozáshoz)."""
        self.metadata = self._default_metadata()
        if os.path.exists(self.metadata_file):
            os.remove(self.metadata_file)
        print("🗑️ Metadata törölve - következő futtatás teljes feldolgozás lesz", flush=True)


# Global singleton instance
_incremental_processor = None

def get_incremental_processor() -> IncrementalProcessor:
    """
    Singleton IncrementalProcessor instance lekérése.
    
    Returns:
        IncrementalProcessor instance
    """
    global _incremental_processor
    if _incremental_processor is None:
        _incremental_processor = IncrementalProcessor()
    return _incremental_processor
