"""
Guild state management for music cogs.
Consolidates all per-guild state into a single class to reduce memory overhead
and simplify state access patterns.
"""
from typing import Optional, Dict, Any, Set
import discord
from dataclasses import dataclass, field


@dataclass
class GuildState:
    """Manages all per-guild music state in a single consolidated object."""
    guild_id: int
    
    # Queue and playback
    queue: list = field(default_factory=list)
    current_song: Optional[Any] = None
    loop_mode: int = 0  # 0: Off, 1: Current, 2: All
    
    # Volume and playback timing
    volume: float = 0.5
    start_time: float = 0.0
    pause_start: Optional[float] = None
    
    # Voting system
    pause_votes: Set[int] = field(default_factory=set)
    skip_votes: Set[int] = field(default_factory=set)
    stop_votes: Set[int] = field(default_factory=set)
    
    # Message tracking
    last_np_msg_id: Optional[int] = None
    last_status_msg_id: Optional[int] = None
    last_channel_id: Optional[int] = None
    
    # Cleanup
    is_cleaning_up: bool = False
    
    def reset_votes(self) -> None:
        """Clear all voting state for fresh track."""
        self.pause_votes.clear()
        self.skip_votes.clear()
        self.stop_votes.clear()
    
    def clear_pause_state(self) -> None:
        """Clear pause-related state."""
        self.pause_start = None
        self.pause_votes.clear()
    
    async def cleanup_message(self, bot: discord.Client) -> None:
        """Safely delete the last now-playing message by id."""
        if not self.last_channel_id or not self.last_np_msg_id:
            return

        channel = bot.get_channel(self.last_channel_id)
        if channel and isinstance(channel, discord.abc.Messageable):
            try:
                old_msg = await channel.fetch_message(self.last_np_msg_id)
                await old_msg.delete()
            except Exception:
                pass
        self.last_np_msg_id = None


class GuildStateManager:
    """Centralized manager for all guild states."""
    
    def __init__(self):
        self.states: Dict[int, GuildState] = {}
    
    def get_or_create(self, guild_id: int) -> GuildState:
        """Get or create a guild state."""
        if guild_id not in self.states:
            self.states[guild_id] = GuildState(guild_id=guild_id)
        return self.states[guild_id]
    
    def get(self, guild_id: int) -> Optional[GuildState]:
        """Get a guild state without creating one."""
        return self.states.get(guild_id)
    
    def remove(self, guild_id: int) -> Optional[GuildState]:
        """Remove and return a guild state."""
        return self.states.pop(guild_id, None)
    
    def has_active_state(self, guild_id: int) -> bool:
        """Check if guild has active state (has queue or is playing)."""
        state = self.get(guild_id)
        if not state:
            return False
        return bool(state.current_song or state.queue)
    
    async def cleanup_guild(self, guild_id: int) -> None:
        """Clean up all resources for a guild."""
        state = self.states.get(guild_id)
        if state:
            state.is_cleaning_up = True
            state.queue.clear()
            state.current_song = None
            state.reset_votes()
    
    async def cleanup_all(self) -> None:
        """Clean up all guild states."""
        for guild_id in list(self.states.keys()):
            await self.cleanup_guild(guild_id)
        self.states.clear()
