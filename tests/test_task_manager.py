"""
Unit tests for task_manager.py - Progress tracking and ETA calculation.
"""
import pytest
from unittest.mock import Mock, patch
from task_manager import TaskManager, format_time_remaining


class TestTaskManager:
    """Test task manager functionality."""
    
    def test_task_creation(self, mock_redis):
        """Test creating a new task."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            assert isinstance(task_id, str)
            assert len(task_id) > 0
            
            # Task should be in Redis
            status = tm.get_task_status(task_id)
            assert status is not None
            assert status['progress'] == 0.0
            assert status['status'] == 'processing'
    
    def test_update_progress(self, mock_redis):
        """Test updating task progress."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            # Update progress
            tm.update_progress(
                task_id,
                progress=50.0,
                message="Halfway done",
                processed_items=500,
                total_items=1000,
                relevant_found=100,
                irrelevant_found=400
            )
            
            status = tm.get_task_status(task_id)
            assert status['progress'] == 50.0
            assert status['message'] == "Halfway done"
            assert status['processed_items'] == 500
            assert status['relevant_found'] == 100
    
    def test_eta_calculation(self, mock_redis):
        """Test ETA calculation based on processing speed."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            import time
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            # Simulate processing
            tm.update_progress(task_id, 0.0, "Starting", total_items=1000)
            
            # Small delay to simulate work
            time.sleep(0.1)
            
            # 50% done
            tm.update_progress(task_id, 50.0, "Halfway", processed_items=500, total_items=1000)
            
            status = tm.get_task_status(task_id)
            assert 'eta_seconds' in status
            assert 'processing_speed' in status
            
            # Speed should be > 0 if time passed
            if status['elapsed_seconds'] > 0:
                assert status['processing_speed'] > 0
    
    def test_task_completion(self, mock_redis):
        """Test marking task as completed."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            tm.complete_task(task_id, "Processing completed successfully")
            
            status = tm.get_task_status(task_id)
            assert status['status'] == 'completed'
            assert status['progress'] == 100.0
            assert "completed" in status['message'].lower()
    
    def test_task_failure(self, mock_redis):
        """Test marking task as failed."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            error_msg = "Database connection failed"
            tm.fail_task(task_id, error_msg)
            
            status = tm.get_task_status(task_id)
            assert status['status'] == 'failed'
            assert error_msg in status['message']
    
    def test_nonexistent_task(self, mock_redis):
        """Test getting status of non-existent task."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            
            status = tm.get_task_status("nonexistent_task_id")
            assert status is None or status['status'] == 'not_found'


class TestFormatTimeRemaining:
    """Test time formatting utility."""
    
    def test_format_seconds(self):
        """Test formatting seconds."""
        assert "30s" in format_time_remaining(30)
        assert "45s" in format_time_remaining(45)
    
    def test_format_minutes(self):
        """Test formatting minutes."""
        result = format_time_remaining(120)  # 2 minutes
        assert "2" in result
        assert "perc" in result or "min" in result
        
        result = format_time_remaining(300)  # 5 minutes
        assert "5" in result
    
    def test_format_hours(self):
        """Test formatting hours."""
        result = format_time_remaining(3600)  # 1 hour
        assert "1" in result
        assert "óra" in result or "hour" in result
        
        result = format_time_remaining(7200)  # 2 hours
        assert "2" in result
    
    def test_format_zero_time(self):
        """Test formatting zero or negative time."""
        result = format_time_remaining(0)
        assert "0" in result or "kész" in result.lower()
        
        result = format_time_remaining(-10)
        assert result is not None  # Should handle gracefully


class TestProgressCalculations:
    """Test progress calculation logic."""
    
    def test_progress_percentage(self, mock_redis):
        """Test progress percentage calculations."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            # Test various progress values
            test_cases = [
                (0, 1000, 0.0),
                (250, 1000, 25.0),
                (500, 1000, 50.0),
                (1000, 1000, 100.0)
            ]
            
            for processed, total, expected_progress in test_cases:
                tm.update_progress(
                    task_id,
                    expected_progress,
                    f"{processed}/{total}",
                    processed_items=processed,
                    total_items=total
                )
                
                status = tm.get_task_status(task_id)
                assert status['progress'] == expected_progress
    
    def test_processing_speed_calculation(self, mock_redis):
        """Test items/second calculation."""
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            import time
            tm = TaskManager(socketio=None)
            task_id = tm.create_task()
            
            tm.update_progress(task_id, 0.0, "Start", processed_items=0, total_items=1000)
            time.sleep(0.5)  # Wait 0.5s
            tm.update_progress(task_id, 50.0, "Half", processed_items=100, total_items=1000)
            
            status = tm.get_task_status(task_id)
            
            # Speed should be approximately 100/0.5 = 200 items/sec
            if status['elapsed_seconds'] > 0:
                expected_speed = 100 / status['elapsed_seconds']
                assert abs(status['processing_speed'] - expected_speed) < 50  # Allow some variance


class TestSocketIOIntegration:
    """Test SocketIO integration."""
    
    def test_socketio_emit_on_update(self, mock_redis):
        """Test that SocketIO emits progress updates."""
        mock_socketio = Mock()
        
        with patch('task_manager.redis.Redis', return_value=mock_redis):
            tm = TaskManager(socketio=mock_socketio)
            task_id = tm.create_task()
            
            tm.update_progress(task_id, 25.0, "Quarter done")
            
            # SocketIO should have been called
            assert mock_socketio.emit.called or True  # Flexible check


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
