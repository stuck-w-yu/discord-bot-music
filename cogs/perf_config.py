from typing import Dict


class OptimizedFFmpegOptions:
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
        if mode.lower() == 'low_latency':
            return OptimizedFFmpegOptions.LOW_LATENCY.copy()
        return OptimizedFFmpegOptions.STANDARD.copy()
