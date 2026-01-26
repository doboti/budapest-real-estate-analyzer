#!/usr/bin/env python3
"""
Check if the improved LLM prompt fixed the e1eb80b1dd48a420 article issue
"""
import redis
import json

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Check the problematic article
article_id = 'e1eb80b1dd48a420'

# Get raw article data
raw_data = r.hget('article_details', article_id)
if raw_data:
    article = json.loads(raw_data)
    print(f"\n{'='*80}")
    print(f"ARTICLE: {article_id}")
    print(f"{'='*80}")
    print(f"Title: {article.get('title', 'N/A')}")
    print(f"Description length: {len(article.get('description', ''))} chars")
    print(f"Description: {article.get('description', 'N/A')[:200]}")
    print()

# Get filtering result
result_key = f'article_relevant:{article_id}'
result_data = r.get(result_key)
if result_data:
    result = json.loads(result_data)
    print(f"WORKER FILTER:")
    print(f"  Needs LLM: {result.get('needs_llm', 'N/A')}")
    print(f"  Worker decision: {result.get('relevant', 'N/A')}")
    print(f"  Worker reason: {result.get('reason', 'N/A')}")
    print()
    
    if result.get('needs_llm'):
        print(f"LLM ANALYSIS:")
        print(f"  Relevant: {result.get('relevant', 'N/A')}")
        print(f"  Reason: {result.get('reason', 'N/A')}")
        print(f"  Property category: {result.get('property_category', 'N/A')}")
        print()
        
        # Check if it mentions "ikerház Csillaghegyen" (the hallucination)
        reason = result.get('reason', '').lower()
        if 'ikerház' in reason or 'csillaghegy' in reason:
            print("❌ STILL HALLUCINATING - mentions ikerház/Csillaghegy")
        elif 'panellakás' in reason or 'xi. kerület' in reason or 'gazdagrét' in reason:
            print("✅ CORRECTLY IDENTIFIED - mentions panellakás/XI.kerület/Gazdagrét")
        else:
            print(f"⚠️  UNCLEAR - reason: '{result.get('reason', '')}'")
else:
    print("⏳ Article not processed yet - wait for processing to complete")

print(f"\n{'='*80}\n")

# Also check the actual ikerház in Csillaghegy for comparison
ikerhaz_id = '468b63dddb255b7b'
result_data2 = r.get(f'article_relevant:{ikerhaz_id}')
if result_data2:
    result2 = json.loads(result_data2)
    print(f"COMPARISON - Actual ikerház {ikerhaz_id}:")
    print(f"  Relevant: {result2.get('relevant', 'N/A')}")
    print(f"  Reason: {result2.get('reason', 'N/A')}")
    print()
