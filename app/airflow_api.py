"""
Airflow REST API integráció a Flask webapp számára.
Helyettesíti az RQ-alapú run-pipeline endpointokat.
"""

import requests
import os
from typing import Dict, Any


class AirflowAPIClient:
    """Airflow REST API kliens"""
    
    def __init__(self):
        self.base_url = os.getenv('AIRFLOW_API_URL', 'http://airflow-webserver:8080/api/v1')
        self.username = os.getenv('AIRFLOW_USERNAME', 'admin')
        self.password = os.getenv('AIRFLOW_PASSWORD', 'admin')
        self.auth = (self.username, self.password)
    
    def trigger_dag(self, dag_id: str, conf: Dict = None) -> Dict[str, Any]:
        """
        Airflow DAG trigger (manuális futtatás indítása)
        
        Args:
            dag_id: DAG azonosító (pl. 'ingatlan_llm_pipeline')
            conf: Konfiguráció dictionary (pl. test_mode flag)
        
        Returns:
            DAG run információ (run_id, state, stb.)
        """
        url = f"{self.base_url}/dags/{dag_id}/dagRuns"
        payload = {
            "conf": conf or {},
            "note": "Manuális trigger a Flask webapp-ból"
        }
        
        try:
            response = requests.post(url, json=payload, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"❌ Airflow API hiba: {e}")
            return {'error': str(e)}
    
    def get_dag_run_status(self, dag_id: str, dag_run_id: str) -> Dict[str, Any]:
        """
        DAG run állapot lekérése
        
        Args:
            dag_id: DAG azonosító
            dag_run_id: Run azonosító (a trigger_dag visszatérési értékében)
        
        Returns:
            Állapot információ (state, start_date, end_date, stb.)
        """
        url = f"{self.base_url}/dags/{dag_id}/dagRuns/{dag_run_id}"
        
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"❌ Airflow API hiba: {e}")
            return {'error': str(e)}
    
    def get_task_instances(self, dag_id: str, dag_run_id: str) -> list:
        """
        DAG run task instance-ok lekérése (részletes haladás)
        
        Args:
            dag_id: DAG azonosító
            dag_run_id: Run azonosító
        
        Returns:
            Task instance lista (task_id, state, duration, stb.)
        """
        url = f"{self.base_url}/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances"
        
        try:
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('task_instances', [])
        except requests.RequestException as e:
            print(f"❌ Airflow API hiba: {e}")
            return []
    
    def pause_dag(self, dag_id: str) -> bool:
        """DAG szüneteltetés (automatikus ütemezés kikapcsolása)"""
        url = f"{self.base_url}/dags/{dag_id}"
        payload = {"is_paused": True}
        
        try:
            response = requests.patch(url, json=payload, auth=self.auth, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"❌ Airflow API hiba: {e}")
            return False
    
    def unpause_dag(self, dag_id: str) -> bool:
        """DAG aktiválás (automatikus ütemezés bekapcsolása)"""
        url = f"{self.base_url}/dags/{dag_id}"
        payload = {"is_paused": False}
        
        try:
            response = requests.patch(url, json=payload, auth=self.auth, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"❌ Airflow API hiba: {e}")
            return False


# Singleton instance
_airflow_client = None

def get_airflow_client() -> AirflowAPIClient:
    """Airflow API kliens singleton getter"""
    global _airflow_client
    if _airflow_client is None:
        _airflow_client = AirflowAPIClient()
    return _airflow_client
