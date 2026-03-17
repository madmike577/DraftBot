"""
sports/__init__.py — Registers all sport handlers.
Import SPORT_HANDLERS anywhere you need to dispatch by sport name.
"""

from sports.ucl     import handler as ucl_handler
from sports.nba     import handler as nba_handler
from sports.f1      import handler as f1_handler
from sports.indycar import handler as indycar_handler
from sports.ncaa    import handler as ncaa_handler

SPORT_HANDLERS = [
    ucl_handler,
    nba_handler,
    f1_handler,
    indycar_handler,
    ncaa_handler,
]
