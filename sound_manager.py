# coding: utf-8
import os
from PyQt6.QtCore import QObject
from config import get_logger

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    winsound = None
    HAS_WINSOUND = False

logger = get_logger()


class SoundManager(QObject):
    """Windows 原生音效播放：无额外线程，异步不卡 UI。非 Windows 静默。"""

    def __init__(self, parent, get_resource_path, volume: float = 0.8):
        super().__init__(parent)
        self._get_resource = get_resource_path
        # winsound 走系统全局音量，不支持单独软件音量
        self._volume = volume
        self._sound_cache = {}
        self._preload_defaults()

    def _preload_defaults(self):
        """预缓存音效文件路径，避免每次查找。"""
        if not HAS_WINSOUND:
            logger.info("非Windows平台，音效播放已禁用")
            return
        logger.debug("开始预加载默认音效...")
        for name in ["assets/alert.wav"]:
            path = self._get_resource(name)
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                self._sound_cache[name] = abs_path
                logger.debug(f"音效预加载成功：{name} -> {abs_path}")
            else:
                logger.warning(f"音效文件不存在：{name} -> {abs_path}")
        logger.debug(f"预加载完成，已缓存：{list(self._sound_cache.keys())}")

    def play(self, sound_name: str):
        """播放音效，异步非阻塞，失败静默。"""
        if not HAS_WINSOUND:
            logger.debug(f"非Windows平台，忽略播放请求：{sound_name}")
            return

        sound_path = self._sound_cache.get(sound_name)
        if not sound_path:
            sound_path = os.path.abspath(self._get_resource(sound_name))
            if os.path.exists(sound_path):
                self._sound_cache[sound_name] = sound_path
            else:
                logger.warning(f"播放失败：文件不存在 {sound_path}")
                return

        try:
            winsound.PlaySound(
                sound_path,
                winsound.SND_FILENAME | winsound.SND_ASYNC)
            logger.debug(f"播放成功：{sound_name}")
        except Exception as e:
            logger.error(f"音效播放失败: {e}")