"""
sports/base.py — Abstract base class that every sport handler implements.
Adding a new sport = create a file, subclass SportHandler, export `handler`.
"""

from abc import ABC, abstractmethod
import discord


class SportHandler(ABC):
    """
    Each sport module exports one instance of a SportHandler subclass.
    The schedule cog iterates SPORT_HANDLERS and calls handler.handles(sport)
    to dispatch to the right module — no more giant if/elif chains.
    """

    @property
    @abstractmethod
    def sport_names(self) -> list[str]:
        """
        List of sport strings as they appear in pick_history['sport'].
        Also includes any display-name aliases used in required_sports.
        Example: ['NCAAM Basketball', "NCAA Basketball - Men's"]
        """
        ...

    def handles(self, sport: str) -> bool:
        """Return True if this handler owns the given sport string."""
        return sport in self.sport_names

    @abstractmethod
    async def schedule(
        self,
        interaction: discord.Interaction,
        league: dict,
        display: str,
    ) -> None:
        """Handle /brackt schedule for this sport."""
        ...

    @abstractmethod
    async def nextmatch(
        self,
        interaction: discord.Interaction,
        league: dict,
    ) -> None:
        """Handle /brackt nextmatch for this sport. Always ephemeral."""
        ...
