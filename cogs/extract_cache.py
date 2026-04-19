"""
Caching layer for extracted track information.
Reduces redundant yt-dlp/Spotify extraction calls for repeated queries.
"""
import time
from typing import Optional, Dict, Any
from collections import OrderedDict


class ExtractInfoCache:
    """LRU cache with TTL for extracted track information."""
    
    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        """
        Initialize cache.
        
        Args:
            max_size: Maximum number of cached items (default 100)
            ttl_seconds: Time-to-live for cache entries in seconds (default 1 hour)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, tuple] = {}  # {query: (timestamp, data)}
        self.access_order = OrderedDict()  # Track LRU order
    
    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Get cached data if it exists and hasn't expired."""
        if query not in self.cache:
            return None
        
        timestamp, data = self.cache[query]
        
        # Check if expired
        if time.time() - timestamp > self.ttl_seconds:
            self._remove(query)
            return None
        
        # Update LRU order
        self.access_order.move_to_end(query)
        return data
    
    def set(self, query: str, data: Dict[str, Any]) -> None:
        """Cache extracted data with current timestamp."""
        if query in self.cache:
            self.access_order.move_to_end(query)
        else:
            # Remove oldest if at capacity
            if len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.access_order))
                self._remove(oldest_key)
        
        self.cache[query] = (time.time(), data)
        self.access_order[query] = True
    
    def _remove(self, query: str) -> None:
        """Remove a cache entry."""
        self.cache.pop(query, None)
        self.access_order.pop(query, None)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()
        self.access_order.clear()
    
    def cleanup_expired(self) -> None:
        """Remove all expired entries."""
        current_time = time.time()
        expired_keys = [
            query for query, (timestamp, _) in self.cache.items()
            if current_time - timestamp > self.ttl_seconds
        ]
        for query in expired_keys:
            self._remove(query)
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'expired_entries': sum(
                1 for timestamp, _ in self.cache.values()
                if time.time() - timestamp > self.ttl_seconds
            )
        }
