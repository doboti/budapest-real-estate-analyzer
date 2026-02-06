"""
Unit tests for incremental_processing.py - Hash-based change detection.
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
from incremental_processing import IncrementalProcessor


class TestIncrementalProcessor:
    """Test incremental processing with hash-based change detection."""
    
    @pytest.fixture
    def temp_metadata_file(self):
        """Create temporary metadata file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        yield temp_path
        Path(temp_path).unlink(missing_ok=True)
    
    def test_processor_initialization(self, mock_redis, temp_metadata_file):
        """Test processor initializes correctly."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            assert processor.metadata_file == temp_metadata_file
            assert processor.article_hashes == {}
    
    def test_generate_article_hash(self, mock_redis, temp_metadata_file):
        """Test SHA256 hash generation for articles."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            article = pd.Series({
                'description': 'Beautiful apartment',
                'title': '2 room flat',
                'price': 50000000,
                'area': 65,
                'district': 'V. kerület'
            })
            
            hash1 = processor.generate_hash(article)
            assert isinstance(hash1, str)
            assert len(hash1) == 64  # SHA256 hex length
            
            # Same data should produce same hash
            hash2 = processor.generate_hash(article)
            assert hash1 == hash2
    
    def test_hash_changes_with_data(self, mock_redis, temp_metadata_file):
        """Test hash changes when article data changes."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            article1 = pd.Series({
                'description': 'Apartment A',
                'title': 'Title A',
                'price': 50000000,
                'area': 65,
                'district': 'V. kerület'
            })
            
            article2 = pd.Series({
                'description': 'Apartment A',
                'title': 'Title A',
                'price': 55000000,  # Price changed!
                'area': 65,
                'district': 'V. kerület'
            })
            
            hash1 = processor.generate_hash(article1)
            hash2 = processor.generate_hash(article2)
            assert hash1 != hash2  # Different price = different hash
    
    def test_filter_new_and_changed(self, mock_redis, temp_metadata_file, sample_article_data):
        """Test filtering new and changed articles."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            # Create test DataFrame
            df = pd.DataFrame([
                {**sample_article_data, 'article_id': 'A1', 'price': 50000000},
                {**sample_article_data, 'article_id': 'A2', 'price': 60000000},
                {**sample_article_data, 'article_id': 'A3', 'price': 70000000}
            ])
            
            # First run - all articles are new
            filtered_df, hashes = processor.filter_new_and_changed(df)
            assert len(filtered_df) == 3
            assert len(hashes) == 3
            
            # Second run - no changes, should return empty
            processor.article_hashes = hashes
            filtered_df2, _ = processor.filter_new_and_changed(df)
            assert len(filtered_df2) == 0
            
            # Third run - one price changed
            df.loc[0, 'price'] = 55000000
            filtered_df3, _ = processor.filter_new_and_changed(df)
            assert len(filtered_df3) == 1
            assert filtered_df3.iloc[0]['article_id'] == 'A1'
    
    def test_metadata_persistence(self, mock_redis, temp_metadata_file):
        """Test saving and loading metadata."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            # Add some hashes
            processor.article_hashes = {
                'article_1': 'hash123',
                'article_2': 'hash456'
            }
            processor.last_processing_time = '2026-01-30T10:00:00'
            
            # Save metadata
            processor.save_metadata()
            
            # Load in new processor instance
            processor2 = IncrementalProcessor(metadata_file=temp_metadata_file)
            processor2.load_metadata()
            
            assert processor2.article_hashes == processor.article_hashes
            assert processor2.last_processing_time == processor.last_processing_time
    
    def test_reset_metadata(self, mock_redis, temp_metadata_file):
        """Test resetting metadata for full reprocessing."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            processor.article_hashes = {'art1': 'hash1'}
            processor.save_metadata()
            
            # Reset
            processor.reset_metadata()
            
            assert processor.article_hashes == {}
            assert not Path(temp_metadata_file).exists()
    
    def test_get_stats(self, mock_redis, temp_metadata_file):
        """Test statistics retrieval."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            processor.article_hashes = {'a1': 'h1', 'a2': 'h2'}
            processor.last_processing_time = '2026-01-30'
            
            stats = processor.get_stats()
            assert stats['tracked_articles'] == 2
            assert stats['last_processing'] == '2026-01-30'
            assert 'metadata_file_exists' in stats


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_missing_metadata_file(self, mock_redis):
        """Test handling of missing metadata file."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file='/nonexistent/path.json')
            processor.load_metadata()  # Should not crash
            assert processor.article_hashes == {}
    
    def test_corrupted_metadata_file(self, mock_redis, temp_metadata_file):
        """Test handling of corrupted JSON metadata."""
        # Write invalid JSON
        with open(temp_metadata_file, 'w') as f:
            f.write("invalid json{{{")
        
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            processor.load_metadata()  # Should handle gracefully
            assert processor.article_hashes == {}
    
    def test_empty_dataframe(self, mock_redis, temp_metadata_file):
        """Test filtering empty DataFrame."""
        with patch('incremental_processing.redis.Redis', return_value=mock_redis):
            processor = IncrementalProcessor(metadata_file=temp_metadata_file)
            
            empty_df = pd.DataFrame()
            filtered, hashes = processor.filter_new_and_changed(empty_df)
            
            assert len(filtered) == 0
            assert len(hashes) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
