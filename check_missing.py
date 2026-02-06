import pandas as pd

# Fájlok betöltése
core = pd.read_parquet('/workspace/parquet/core_data.parquet')
filtered = pd.read_parquet('/workspace/parquet/core_layer_filtered.parquet')
irrelevant = pd.read_parquet('/workspace/parquet/core_layer_irrelevant.parquet')

# Article ID-k kinyerése
core_ids = set(core['article_id'])
filtered_ids = set(filtered['article_id'])
irrelevant_ids = set(irrelevant['article_id'])

# Feldolgozott article_id-k (filtered VAGY irrelevant)
processed = filtered_ids | irrelevant_ids

# Hiányzó article_id-k (core-ban van, de nincs feldolgozva)
missing = core_ids - processed

# Eredmények
print(f'Core_data: {len(core_ids)} egyedi article_id')
print(f'Filtered: {len(filtered_ids)} article_id')
print(f'Irrelevant: {len(irrelevant_ids)} article_id')
print(f'Összesen feldolgozva: {len(processed)} article_id')
print(f'HIÁNYZIK (nincs sem filtered sem irrelevant): {len(missing)} article_id')

if len(missing) > 0:
    percentage = len(missing) / len(core_ids) * 100
    print(f'Hiányzó százalék: {percentage:.1f}%')
    print(f'\nPélda hiányzó article_id-k (első 5):')
    for aid in list(missing)[:5]:
        print(f'  - {aid}')
