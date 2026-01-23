"""
Parquet streaming utilities for memory-efficient processing.
Implements chunked reading with memory mapping for large datasets.
"""

import pandas as pd
import pyarrow.parquet as pq
from typing import Iterator, Optional, Set
import os


class ParquetStreamReader:
    """
    Memory-efficient Parquet file reader using chunked processing and memory mapping.
    
    Example:
        reader = ParquetStreamReader('large_file.parquet', chunk_size=10000)
        for chunk_df in reader.iter_chunks():
            # Process chunk
            pass
    """
    
    def __init__(self, file_path: str, chunk_size: int = 10000, use_memory_map: bool = True):
        """
        Initialize the stream reader.
        
        Args:
            file_path: Path to the Parquet file
            chunk_size: Number of rows per chunk
            use_memory_map: Whether to use memory mapping (reduces RAM usage)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Parquet file not found: {file_path}")
        
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.use_memory_map = use_memory_map
        
        # Get file metadata
        self.parquet_file = pq.ParquetFile(file_path, memory_map=use_memory_map)
        self.total_rows = self.parquet_file.metadata.num_rows
        self.num_chunks = (self.total_rows + chunk_size - 1) // chunk_size
        
    def iter_chunks(self) -> Iterator[pd.DataFrame]:
        """
        Iterate through the Parquet file in chunks.
        
        Yields:
            DataFrame chunks with max chunk_size rows
        """
        for i in range(self.num_chunks):
            start_row = i * self.chunk_size
            end_row = min((i + 1) * self.chunk_size, self.total_rows)
            
            # Read chunk using PyArrow for efficiency
            table = self.parquet_file.read_row_group(
                i % self.parquet_file.num_row_groups,
                columns=None,
                use_threads=True
            ) if self.parquet_file.num_row_groups > 1 else self.parquet_file.read()
            
            # Convert to pandas DataFrame
            chunk_df = table.to_pandas()
            
            # Slice to exact chunk size if needed
            actual_start = start_row % len(chunk_df)
            actual_end = min(actual_start + (end_row - start_row), len(chunk_df))
            
            if actual_start < len(chunk_df):
                yield chunk_df.iloc[actual_start:actual_end]
    
    def iter_batches_pyarrow(self, batch_size: int = 10000) -> Iterator[pd.DataFrame]:
        """
        Iterate using PyArrow's native batch iterator (more efficient).
        
        Args:
            batch_size: Number of rows per batch
            
        Yields:
            DataFrame batches
        """
        # Use PyArrow's built-in batch iterator
        for batch in self.parquet_file.iter_batches(batch_size=batch_size):
            yield batch.to_pandas()
    
    def get_unique_values_streaming(self, column: str) -> Set:
        """
        Get unique values from a column without loading entire file into memory.
        
        Args:
            column: Column name to get unique values from
            
        Returns:
            Set of unique values
        """
        unique_values = set()
        
        for chunk in self.iter_batches_pyarrow(batch_size=50000):
            if column in chunk.columns:
                unique_values.update(chunk[column].dropna().unique())
        
        return unique_values
    
    def __repr__(self) -> str:
        return (f"ParquetStreamReader(file='{self.file_path}', "
                f"total_rows={self.total_rows}, "
                f"chunk_size={self.chunk_size}, "
                f"num_chunks={self.num_chunks})")


def read_parquet_chunked(
    file_path: str,
    chunk_size: int = 10000,
    columns: Optional[list] = None,
    filter_func: Optional[callable] = None
) -> Iterator[pd.DataFrame]:
    """
    Read Parquet file in chunks with optional filtering.
    
    Args:
        file_path: Path to Parquet file
        chunk_size: Rows per chunk
        columns: Specific columns to read (None = all)
        filter_func: Optional function to filter chunks (chunk_df -> filtered_df)
        
    Yields:
        Filtered DataFrame chunks
        
    Example:
        for chunk in read_parquet_chunked('data.parquet', chunk_size=5000):
            process(chunk)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    parquet_file = pq.ParquetFile(file_path, memory_map=True)
    
    for batch in parquet_file.iter_batches(batch_size=chunk_size, columns=columns):
        chunk_df = batch.to_pandas()
        
        if filter_func:
            chunk_df = filter_func(chunk_df)
        
        if len(chunk_df) > 0:
            yield chunk_df


def get_unique_articles_streaming(
    file_path: str,
    article_id_column: str = 'article_id',
    chunk_size: int = 50000,
    exclude_ids: Optional[Set] = None
) -> pd.DataFrame:
    """
    Get unique articles from a large Parquet file without loading everything into memory.
    
    Args:
        file_path: Path to Parquet file
        article_id_column: Name of the article ID column
        chunk_size: Chunk size for streaming
        exclude_ids: Set of article IDs to exclude (already processed)
        
    Returns:
        DataFrame with unique articles (one row per article_id)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    seen_ids = exclude_ids or set()
    unique_articles = []
    
    reader = ParquetStreamReader(file_path, chunk_size=chunk_size)
    
    for chunk in reader.iter_batches_pyarrow(batch_size=chunk_size):
        # Filter out already seen IDs
        new_articles = chunk[~chunk[article_id_column].isin(seen_ids)]
        
        if len(new_articles) > 0:
            # Deduplicate within this chunk
            new_articles = new_articles.drop_duplicates(subset=[article_id_column])
            
            # Add to result
            unique_articles.append(new_articles)
            
            # Update seen IDs
            seen_ids.update(new_articles[article_id_column].values)
    
    # Combine all unique articles
    if unique_articles:
        return pd.concat(unique_articles, ignore_index=True)
    else:
        return pd.DataFrame()


def estimate_parquet_memory(file_path: str) -> dict:
    """
    Estimate memory requirements for a Parquet file.
    
    Returns:
        Dictionary with file info and memory estimates
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    
    parquet_file = pq.ParquetFile(file_path)
    total_rows = parquet_file.metadata.num_rows
    num_columns = len(parquet_file.schema)
    
    # Rough estimate: Parquet is typically 3-10x compressed
    estimated_memory_mb = file_size_mb * 5  # Conservative estimate
    
    # Recommended chunk size to keep memory under 500MB per chunk
    recommended_chunk_size = max(1000, int((500 / estimated_memory_mb) * total_rows))
    
    return {
        'file_size_mb': round(file_size_mb, 2),
        'total_rows': total_rows,
        'num_columns': num_columns,
        'estimated_memory_mb': round(estimated_memory_mb, 2),
        'recommended_chunk_size': recommended_chunk_size,
        'compression_ratio': round(estimated_memory_mb / file_size_mb, 2)
    }
