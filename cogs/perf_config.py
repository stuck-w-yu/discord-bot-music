"""
Performance optimization configuration for music bot.
Includes optimized FFmpeg and yt-dlp settings for better latency and resource usage.
"""
from typing import Dict, Any


class OptimizedFFmpegOptions:
    """Optimized FFmpeg options for lower latency and better stability."""
    
    # Standard production settings
    STANDARD = {
        'before_options': (
            '-reconnect 1 '
            '-reconnect_streamed 1 '
            '-reconnect_at_eof 1 '
            '-reconnect_on_network_error 1 '
            '-reconnect_delay_max 5 '
            '-rw_timeout 15000000 '
            '-user_agent "Mozilla/5.0"'
        ),
        'options': '-vn -probesize 32 -analyzeduration 0 -bufsize 64k -fflags +nobuffer',
    }
    
    # Low latency settings (for faster startup)
    LOW_LATENCY = {
        'before_options': (
            '-reconnect 1 '
            '-reconnect_streamed 1 '
            '-reconnect_at_eof 1 '
            '-reconnect_on_network_error 1 '
            '-reconnect_delay_max 3 '
            '-rw_timeout 10000000'
        ),
        'options': '-vn -probesize 32 -analyzeduration 0 -bufsize 32k -tune zerolatency',
    }
    
    @staticmethod
    def get(mode: str = 'standard') -> Dict[str, str]:
        """Get FFmpeg options for a specific mode."""
        if mode.lower() == 'low_latency':
            return OptimizedFFmpegOptions.LOW_LATENCY.copy()
        return OptimizedFFmpegOptions.STANDARD.copy()


class OptimizedYtdlpOptions:
    """Optimized yt-dlp options for faster extraction and better compatibility."""
    
    # Fast extraction (for single tracks)
    FAST = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': False,
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        'socket_timeout': 30,
        'skip_download': True,  # Critical: don't download audio file
    }
    
    # Full extraction (with all metadata)
    FULL = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': False,
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        'socket_timeout': 30,
        'skip_download': True,
    }
    
    @staticmethod
    def get(mode: str = 'fast') -> Dict[str, Any]:
        """Get yt-dlp options for a specific mode."""
        if mode.lower() == 'full':
            return OptimizedYtdlpOptions.FULL.copy()
        return OptimizedYtdlpOptions.FAST.copy()


class BotPerformanceConfig:
    """Bot-wide performance configuration."""
    
    # Queue management
    MAX_QUEUE_SIZE = 500  # Maximum songs in queue per guild
    QUEUE_WARNING_THRESHOLD = 400  # Warn user when queue gets close to max
    
    # Caching
    EXTRACT_CACHE_MAX_SIZE = 100  # LRU cache size for extracted info
    EXTRACT_CACHE_TTL_SECONDS = 3600  # 1 hour TTL for cached extractions
    
    # Timeout settings
    EXTRACTION_TIMEOUT_SECONDS = 30
    VOICE_CONNECT_TIMEOUT_SECONDS = 10
    
    # Resource cleanup
    CLEANUP_EMPTY_GUILD_STATE_AFTER_SECONDS = 3600  # Clean up inactive guilds after 1 hour
    MESSAGE_CLEANUP_DELAY_SECONDS = 0.5  # Delay before deleting old now-playing messages
    
    # Concurrency limits
    MAX_CONCURRENT_EXTRACTIONS = 3  # Limit concurrent yt-dlp/Spotify operations
    
    # Memory management
    DISABLE_DISK_CACHE = False  # Set to True to disable yt-dlp disk caching for lower I/O
    
    @staticmethod
    def as_dict() -> Dict[str, Any]:
        """Export configuration as dictionary."""
        return {
            'max_queue_size': BotPerformanceConfig.MAX_QUEUE_SIZE,
            'queue_warning_threshold': BotPerformanceConfig.QUEUE_WARNING_THRESHOLD,
            'extract_cache_max_size': BotPerformanceConfig.EXTRACT_CACHE_MAX_SIZE,
            'extract_cache_ttl_seconds': BotPerformanceConfig.EXTRACT_CACHE_TTL_SECONDS,
            'extraction_timeout_seconds': BotPerformanceConfig.EXTRACTION_TIMEOUT_SECONDS,
            'voice_connect_timeout_seconds': BotPerformanceConfig.VOICE_CONNECT_TIMEOUT_SECONDS,
        }
