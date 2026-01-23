import pandas as pd
import ollama
import json
import os
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Dict, Any
from parquet_streaming import (
    ParquetStreamReader,
    get_unique_articles_streaming,
    estimate_parquet_memory
)

# Constants
INPUT_FILE = '/workspace/core_data.parquet'
OUTPUT_FILE = '/workspace/core_layer_filtered.parquet'
IRRELEVANT_OUTPUT_FILE = '/workspace/core_layer_irrelevant.parquet'
LOG_FILE = '/workspace/llm_decisions_log.csv'
MODEL_NAME = 'llama3.2:3b'

PROMPT_TEMPLATE = """
Feladat: Ingatlanleírás alapján döntsd el a relevanciát és nyerd ki a strukturált adatokat.
Alapértelmezés: Az ingatlan releváns (true), kivéve, ha kizáró okot találsz.

Kizáró okok (`relevant: false`):
- Nem 1/1 tulajdon vagy nem tiszta eladás (pl. osztatlan közös, tulajdoni hányad, bérleti jog, haszonélvezet, önkormányzati, csere).
- Ingatlan típusa: Kizáró ok, ha nem "lakás", "társasházi lakás", vagy "félszuterén lakás". Például a telek, garázs, nyaraló, ikerház, családi ház NEM releváns.
- Nem budapesti.
- "Csak készpénzes vevőknek" (ez gyakran jogi problémát jelez).

Strukturált adatok:
- Emelet (`floor`): Szám (pl. 1, 2). Földszint: 0. Szuterén/félszuterén: -1. Ha nincs info: null.
- Utca (`street`): Az ingatlan utcaneve (pl. 'Kossuth Lajos utca'). Ha nincs: null.
- Építési mód (`building_type`): "tegla" ha tégla épület, "panel" ha panelház, "egyeb" ha más (pl. vályog, favázas), null ha nincs info.
- Ingatlan kategória (`property_category`): "lakas" vagy "haz". A társasházi lakás = "lakas". Ha nincs info: null.
- Terasz (`has_terrace`): true ha van terasz/erkély/loggia/franciaerkély, false ha nincs vagy nem említi, null ha nem egyértelmű.

Leírás: {description}

Formátum: A válaszod CSAK egy JSON objektum legyen, extra szöveg nélkül.
Példa: {{"relevant": true, "reason": "", "floor": 1, "street": "Egészségház utca", "building_type": "tegla", "property_category": "lakas", "has_terrace": true}}
vagy {{"relevant": false, "reason": "Családi ház", "floor": null, "street": null, "building_type": null, "property_category": "haz", "has_terrace": null}}
"""

# Keywords for the fast, rule-based pre-filter.
# These are high-confidence indicators of irrelevance based on the prompt's rules.
IRRELEVANT_KEYWORDS = {
    # Tulajdonjogi vagy eladási problémák
    "osztatlan közös": "Osztatlan közös tulajdon",
    "tulajdoni hányad": "Tulajdoni hányad",
    "bérleti jog": "Bérleti jog (nem eladás)",
    "haszonélvezet": "Haszonélvezet", # A 'tehermentes' kivételt a rule_based_pre_filter kezeli
    "önkormányzati": "Önkormányzati tulajdon",
    "csere": "Csere (nem eladás)",

    # Ingatlan típusok, amelyek egyértelműen nem társasházi lakások
    "nyaraló": "Ingatlan típusa: Nyaraló",
    "ikerház": "Ingatlan típusa: Ikerház",
    "családi ház": "Ingatlan típusa: Családi ház",
    "üzlethelyiség": "Ingatlan típusa: Üzlethelyiség",
    "iroda": "Ingatlan típusa: Iroda",
    # A 'telek', 'garázs', 'tároló', 'pince' szavakat kivettük, mert gyakran releváns lakásokhoz kapcsolódó
    # extraként szerepelnek, és tévesen szűrtek. Az LLM jobban kezeli ezeket a kontextusokat.

    # Egyéb kizáró okok
    "csak készpénz": "Csak készpénzes vevő (jogi kockázat)",
}

# Words that might negate an irrelevant keyword, making the case ambiguous for the rules.
NEGATION_KEYWORDS = ["tehermentes", "nincs haszonélvezet", "törölve"]

def rule_based_pre_filter(description: str) -> Dict[str, Any] | None:
    """A fast, rule-based pre-filter to identify and reject clearly irrelevant listings."""
    normalized_desc = ' ' + description.lower() + ' '

    if "haszonélvezet" in normalized_desc and any(neg in normalized_desc for neg in NEGATION_KEYWORDS):
        return None  # Ambiguous case (e.g., "tehermentes"), let LLM decide.

    for keyword, reason in IRRELEVANT_KEYWORDS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', normalized_desc):
            return {"relevant": False, "reason": f"Rule-based: {reason}"}

    return None  # Uncertain, requires LLM analysis

def get_llm_decision(description: str) -> Tuple[bool, str, int | None, str | None, str | None, str | None, bool | None]:
    prompt = PROMPT_TEMPLATE.format(description=description)
    
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0}  # Deterministic
        )
        content = response['message']['content']
        
        # Extract JSON from content
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            try:
                result: Dict[str, Any] = json.loads(json_str)
                # Alapértelmezetten False, ha a 'relevant' kulcs hiányzik a JSON-ből
                relevant = result.get('relevant', False)
                reason = result.get('reason', 'No reason provided in JSON.')
                floor = result.get('floor')
                street = result.get('street')
                building_type = result.get('building_type')
                property_category = result.get('property_category')
                has_terrace = result.get('has_terrace')

                # Emelet értékének validálása és konvertálása
                if floor is not None and not isinstance(floor, int):
                    try:
                        floor = int(floor)
                    except (ValueError, TypeError):
                        floor = None # Ha a konverzió sikertelen, legyen None

                return (
                    bool(relevant), 
                    str(reason), 
                    floor, 
                    str(street) if street else None,
                    str(building_type) if building_type else None,
                    str(property_category) if property_category else None,
                    bool(has_terrace) if has_terrace is not None else None
                )
            except json.JSONDecodeError:
                return False, f"Invalid JSON in response: {content}", None, None, None, None, None
        else:
            # Alapértelmezetten False, ha az LLM válasz formátuma nem várt
            return False, f"No JSON object found in response: {content}", None, None, None, None, None
    except Exception as e:
        print(f"Error processing description: {e}")
        return False, f"LLM or network error: {e}", None, None, None, None, None

def process_article(row: pd.Series) -> Tuple[str, bool, str, str, int | None, str | None, str | None, str | None, bool | None]:
    article_id = row['article_id']
    description = row.get('description', '')
    title = row.get('title', '')

    # Ha a leírás hiányzik vagy rövid, használjuk a címet is
    # A cím gyakran tartalmaz fontos információkat (pl. "téglalakás", "erkélyes")
    combined_text = description
    if not description or pd.isna(description) or len(description.strip()) < 100:
        # Ha nincs leírás de van cím, használjuk a címet
        if title and not pd.isna(title) and len(title.strip()) > 10:
            combined_text = f"Cím: {title}\n"
        else:
            # Ha se leírás se cím, akkor feltételezünk relevanciát
            return article_id, True, 'Short or missing description and title, assumed relevant', description, None, None, None, None, None

    # 1. Try the fast, rule-based pre-filter to catch obvious cases
    rule_decision = rule_based_pre_filter(combined_text)
    if rule_decision:
        return article_id, rule_decision['relevant'], rule_decision['reason'], description, rule_decision.get('floor'), None, None, None, None

    # 2. If rules are uncertain, fall back to the LLM for nuanced analysis
    relevant, reason, floor, street, building_type, property_category, has_terrace = get_llm_decision(combined_text)
    return article_id, relevant, f"LLM: {reason}", description, floor, street, building_type, property_category, has_terrace

def main() -> None:
    # Pull model if not available
    ollama.pull(MODEL_NAME)
    
    print("--- Starting data processing ---")
    
    # 🔍 Parquet fájl elemzése streaming módban
    print("📊 Parquet fájl elemzése...")
    file_info = estimate_parquet_memory(INPUT_FILE)
    print(f"   Fájl méret: {file_info['file_size_mb']} MB")
    print(f"   Sorok száma: {file_info['total_rows']}")
    print(f"   Becsült memória: {file_info['estimated_memory_mb']} MB")
    print(f"   Ajánlott chunk méret: {file_info['recommended_chunk_size']}")
    
    # --- Load existing processed results to avoid re-processing ---
    existing_processed_ids = set()
    existing_processed_results = {} # {article_id: {'relevant': bool, 'reason': str, 'floor': int | None, 'street': str | None, ...}}

    if os.path.exists(OUTPUT_FILE):
        filtered_existing_df = pd.read_parquet(OUTPUT_FILE)
        for _, row in filtered_existing_df.iterrows():
            existing_processed_results[row['article_id']] = {
                'relevant': True,
                'reason': row.get('reason_to_relevance', 'Previously filtered as relevant'),
                'floor': row.get('floor'),
                'street': row.get('street'),
                'building_type': row.get('building_type'),
                'property_category': row.get('property_category'),
                'has_terrace': row.get('has_terrace')
            }
            existing_processed_ids.add(row['article_id'])
        print(f"Loaded {len(filtered_existing_df)} existing relevant records from {OUTPUT_FILE}.")

    if os.path.exists(IRRELEVANT_OUTPUT_FILE):
        irrelevant_existing_df = pd.read_parquet(IRRELEVANT_OUTPUT_FILE)
        for _, row in irrelevant_existing_df.iterrows():
            existing_processed_results[row['article_id']] = {
                'relevant': False,
                'reason': row.get('reason_to_relevance', 'Previously filtered as irrelevant'),
                'floor': row.get('floor'),
                'street': row.get('street'),
                'building_type': row.get('building_type'),
                'property_category': row.get('property_category'),
                'has_terrace': row.get('has_terrace')
            }
            existing_processed_ids.add(row['article_id'])
        print(f"Loaded {len(irrelevant_existing_df)} existing irrelevant records from {IRRELEVANT_OUTPUT_FILE}.")
    
    # 💾 Streaming unique articles - chunked processing
    print("🔄 Unique cikkek betöltése streaming módban...")
    unique_articles = get_unique_articles_streaming(
        INPUT_FILE,
        article_id_column='article_id',
        chunk_size=file_info['recommended_chunk_size'],
        exclude_ids=existing_processed_ids
    )
    print(f"Unique articles: {len(unique_articles)}")

    # --- Separate articles to process vs. already processed ---
    articles_to_process = []
    articles_already_processed_log = [] # For articles that were already processed
    
    for _, row in unique_articles.iterrows():
        article_id = row['article_id']
        if article_id in existing_processed_ids:
            result = existing_processed_results[article_id]
            articles_already_processed_log.append({
                'article_id': article_id,
                'description': row.get('description', ''), # Get description from the current row
                'relevant': result['relevant'],
                'reason': result['reason'],
                'floor': result['floor'],
                'street': result['street'],
                'building_type': result.get('building_type'),
                'property_category': result.get('property_category'),
                'has_terrace': result.get('has_terrace')
            })
    
        else:
            articles_to_process.append(row)
    
    print(f"Found {len(articles_already_processed_log)} articles already processed. {len(articles_to_process)} new articles to process.")

    # Process new unique articles in parallel
    new_results_log = []
    total_new_articles = len(articles_to_process)
    
    if total_new_articles > 0:
        with ThreadPoolExecutor(max_workers=4) as executor:  # Adjust max_workers based on your system
            futures = {executor.submit(process_article, row): i for i, row in enumerate(articles_to_process)}
            
            for future in tqdm(as_completed(futures), total=total_new_articles, desc="Processing new articles"):
                article_id, relevant, reason, description, floor, street, building_type, property_category, has_terrace = future.result()
                new_results_log.append({
                    'article_id': article_id,
                    'description': description,
                    'relevant': relevant,
                    'reason': reason,
                    'floor': floor,
                    'street': street,
                    'building_type': building_type,
                    'property_category': property_category,
                    'has_terrace': has_terrace
                })
    
    # Combine all log data (newly processed + already processed)
    full_log_data = articles_already_processed_log + new_results_log
    
    # Save full log
    log_df = pd.DataFrame(full_log_data)
    log_df.to_csv(LOG_FILE, index=False)
    print(f"Saved full processing log to {LOG_FILE}.")
    
    # 💾 Streaming mentés: csak a feldolgozott cikkek sorait keressük meg és mentjük
    print("💾 Eredmények mentése streaming módban...")
    
    processed_ids = set(log_df['article_id'].values)
    relevant_ids = set(log_df[log_df['relevant'] == True]['article_id'].values)
    irrelevant_ids = set(log_df[log_df['relevant'] == False]['article_id'].values)
    
    # Streaming olvasás és mentés
    relevant_rows = []
    irrelevant_rows = []
    
    reader = ParquetStreamReader(INPUT_FILE, chunk_size=file_info['recommended_chunk_size'])
    for chunk in reader.iter_batches_pyarrow(batch_size=50000):
        # Csak a feldolgozott cikkek
        processed_chunk = chunk[chunk['article_id'].isin(processed_ids)]
        
        if len(processed_chunk) > 0:
            # Merge eredményekkel
            chunk_with_results = processed_chunk.merge(
                log_df.rename(columns={'reason': 'reason_to_relevance'})[
                    ['article_id', 'relevant', 'reason_to_relevance', 'floor', 'street', 
                     'building_type', 'property_category', 'has_terrace']
                ],
                on='article_id',
                how='left'
            )
            
            # Szétválasztás releváns/irreleváns
            relevant_chunk = chunk_with_results[chunk_with_results['relevant'] == True]
            irrelevant_chunk = chunk_with_results[chunk_with_results['relevant'] == False]
            
            if len(relevant_chunk) > 0:
                relevant_rows.append(relevant_chunk)
            if len(irrelevant_chunk) > 0:
                irrelevant_rows.append(irrelevant_chunk)
    
    # Összefűzés és mentés
    if relevant_rows:
        filtered_df = pd.concat(relevant_rows, ignore_index=True)
        filtered_df.to_parquet(OUTPUT_FILE, index=False)
        print(f"Saved {len(filtered_df)} relevant records to {OUTPUT_FILE}")
    
    if irrelevant_rows:
        irrelevant_df = pd.concat(irrelevant_rows, ignore_index=True)
        irrelevant_df.to_parquet(IRRELEVANT_OUTPUT_FILE, index=False)
        print(f"Saved {len(irrelevant_df)} irrelevant records for review to {IRRELEVANT_OUTPUT_FILE}")

    print("--- Processing finished ---")
if __name__ == '__main__':
    main()