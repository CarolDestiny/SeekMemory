"""SeekMemory AstrBot entrypoint: composition only."""

from astrbot.api import star

from .adapters.astrbot_hooks import build_astrbot_hooks
from .adapters.astrbot_plugin import AstrBotPlugin


class Main(AstrBotPlugin, star.Star):
    """Thin host entrypoint; behavior lives in adapters and orchestration."""

    initialize = AstrBotPlugin.initialize
    terminate = AstrBotPlugin.terminate
    locals().update(build_astrbot_hooks(__name__))
