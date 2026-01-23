#!/usr/bin/env python3
"""
RQ Worker indító script.
Ez a script indítja a háttérfeladat feldolgozó worker-t.
"""

import os
import sys
from rq import Worker
from task_manager import redis_conn, task_queue

def start_worker():
    """RQ worker indítása."""
    try:
        # Worker létrehozása
        worker = Worker([task_queue], connection=redis_conn)
        
        print("🚀 RQ Worker indítása...")
        print(f"📋 Queue: {task_queue.name}")
        print(f"🔗 Redis host: {os.getenv('REDIS_HOST', 'localhost')}")
        print("⏳ Várakozás feladatokra...")
        
        # Worker indítása (blokkoló hívás)
        worker.work(with_scheduler=True)
        
    except KeyboardInterrupt:
        print("\n👋 Worker leállítása...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Hiba a worker indítása során: {e}")
        sys.exit(1)

if __name__ == '__main__':
    start_worker()