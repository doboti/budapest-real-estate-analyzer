"""
Háttérfeladat kezelő RQ (Redis Queue) alapú aszinkron feldolgozáshoz.
Ez megoldja a Gateway Timeout problémát és real-time progress tracking-et biztosít.
"""

import os
import uuid
import redis
from rq import Queue, Worker
from typing import Dict, Any, Optional
import json
import time
from models import TaskStatus

# Flask-SocketIO import a WebSocket broadcast-hoz
try:
    from flask_socketio import SocketIO
except ImportError:
    # Fallback ha nincs Flask-SocketIO (pl. worker környezetben)
    SocketIO = None

# Redis kapcsolat konfigurálása
redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_conn = redis.Redis(host=redis_host, port=redis_port)  # decode_responses=True eltávolítva

# RQ queue létrehozása
task_queue = Queue('data_processing', connection=redis_conn)

class TaskManager:
    """Feladat állapot kezelő osztály prediktív ETA tracking-gel."""
    
    def __init__(self, socketio = None):
        self.redis_conn = redis_conn
        self.socketio = socketio
        # Throttling: csak 2 másodpercenként frissítsük ugyanazt a task-ot
        self._last_update = {}
        # ETA tracking: kezdési időpontok tárolása
        self._task_start_times = {}
    
    def create_task(self, task_type: str = "data_processing") -> str:
        """Új feladat létrehozása egyedi ID-val."""
        task_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Kezdési időpont tárolása ETA számításhoz
        self._task_start_times[task_id] = start_time
        
        initial_status = TaskStatus(
            task_id=task_id,
            status="pending",
            progress=0.0,
            message="Feladat létrehozva, várakozás indításra...",
            start_time=start_time
        )
        
        self.redis_conn.set(
            f"task_status:{task_id}", 
            initial_status.json(),
            ex=3600  # 1 órás lejárat
        )
        return task_id
    
    def update_progress(self, task_id: str, progress: float, message: str = "", 
                       processed_items: int = 0, relevant_found: int = 0, 
                       irrelevant_found: int = 0, total_items: Optional[int] = None):
        """Feladat haladás frissítése throttling-gal és ETA számítással."""
        # Throttling: ne frissítsük túl gyakran ugyanazt a task-ot
        now = time.time()
        last_update = self._last_update.get(task_id, 0)
        
        # Csak 1 másodpercenként engedélyezzük a frissítést, kivéve ha 100% (befejezett)
        if progress < 100.0 and (now - last_update) < 1.0:
            return True
            
        self._last_update[task_id] = now
        
        # ETA számítás
        start_time = self._task_start_times.get(task_id)
        elapsed_seconds = None
        eta_seconds = None
        items_per_second = None
        estimated_total_seconds = None
        
        if start_time and total_items and total_items > 0:
            elapsed_seconds = now - start_time
            
            # Csak akkor számoljunk ETA-t ha van értelmes haladás (> 1%)
            if processed_items > 0 and progress > 1.0:
                items_per_second = processed_items / elapsed_seconds
                remaining_items = total_items - processed_items
                
                if items_per_second > 0:
                    eta_seconds = remaining_items / items_per_second
                    estimated_total_seconds = elapsed_seconds + eta_seconds
        
        # Formázott ETA üzenet
        eta_message = ""
        if eta_seconds:
            if eta_seconds < 60:
                eta_message = f" | ETA: {int(eta_seconds)}s"
            elif eta_seconds < 3600:
                minutes = int(eta_seconds / 60)
                seconds = int(eta_seconds % 60)
                eta_message = f" | ETA: {minutes}m {seconds}s"
            else:
                hours = int(eta_seconds / 3600)
                minutes = int((eta_seconds % 3600) / 60)
                eta_message = f" | ETA: {hours}h {minutes}m"
        
        print(f"🔄 Task Manager frissítés: {progress:.1f}% - {message}{eta_message} | R:{relevant_found}, I:{irrelevant_found}", flush=True)
        
        current_status = self.get_status(task_id)
        if not current_status:
            return False
        
        updated_status = TaskStatus(
            task_id=task_id,
            status="running" if progress < 100.0 else "completed",
            progress=min(progress, 100.0),
            message=message or current_status.message,
            processed_items=processed_items,
            relevant_found=relevant_found,
            irrelevant_found=irrelevant_found,
            total_items=total_items or current_status.total_items,
            start_time=start_time,
            elapsed_seconds=elapsed_seconds,
            eta_seconds=eta_seconds,
            items_per_second=items_per_second,
            estimated_total_seconds=estimated_total_seconds
        )
        
        self.redis_conn.set(
            f"task_status:{task_id}",
            updated_status.json(),
            ex=3600
        )
        
        # WebSocket broadcast a real-time frissítésekhez
        if self.socketio:
            try:
                self.socketio.emit('status_update', updated_status.model_dump(), room=task_id)
            except Exception as e:
                print(f"WebSocket broadcast hiba: {e}", flush=True)
        
        return True
    
    def set_status(self, task_id: str, status: str, message: str = ""):
        """Feladat státusz beállítása."""
        current_status = self.get_status(task_id)
        if not current_status:
            return False
        
        updated_status = TaskStatus(
            task_id=task_id,
            status=status,
            progress=current_status.progress,
            message=message or current_status.message,
            processed_items=current_status.processed_items,
            relevant_found=current_status.relevant_found,
            irrelevant_found=current_status.irrelevant_found,
            total_items=current_status.total_items
        )
        
        self.redis_conn.set(
            f"task_status:{task_id}",
            updated_status.json(),
            ex=3600
        )
        return True
    
    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        """Feladat státusz lekérdezése."""
        status_json = self.redis_conn.get(f"task_status:{task_id}")
        if not status_json:
            return None
        
        try:
            # Bytes to string konverzió ha szükséges
            if isinstance(status_json, bytes):
                status_json = status_json.decode('utf-8')
            status_data = json.loads(status_json)
            return TaskStatus(**status_data)
        except Exception:
            return None
    
    def mark_failed(self, task_id: str, error_message: str):
        """Feladat sikertelenként megjelölése."""
        self.set_status(task_id, "failed", f"Hiba: {error_message}")
    
    def mark_completed(self, task_id: str, message: str = "Feldolgozás sikeresen befejezve"):
        """Feladat befejezettként megjelölése."""
        self.update_progress(task_id, 100.0, message)
        self.set_status(task_id, "completed", message)

def enqueue_data_processing_task(task_id: str, test_mode: bool = False) -> str:
    """Adatfeldolgozási feladat beütemezése a háttérben.
    
    Args:
        task_id: A feladat azonosítója
        test_mode: Ha True, akkor teszt módban fut (korlátozott elemszám)
    """
    job = task_queue.enqueue(
        'background_tasks.process_data_async',
        task_id,
        test_mode,  # Teszt mód flag átadása
        job_timeout='2h',  # 2 órás timeout (nagy adathalmazokhoz)
        job_id=task_id
    )
    return job.id

def get_queue_status() -> Dict[str, Any]:
    """Queue státusz információk lekérdezése."""
    return {
        'pending_jobs': len(task_queue),
        'failed_jobs': len(task_queue.failed_job_registry),
        'scheduled_jobs': len(task_queue.scheduled_job_registry),
        'workers_count': Worker.count(queue=task_queue)
    }