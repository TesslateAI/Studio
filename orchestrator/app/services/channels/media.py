"""
Media Pipeline — download, cache, and transcribe media from messaging platforms.

Handles voice messages (transcription via LiteLLM → Whisper), images, and
documents. Cached files are evicted after a configurable max age.
"""

import asyncio
import hashlib
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class MediaPipeline:
    """Download, cache, and transcribe media from messaging platforms."""

    def __init__(self, cache_dir: str = "/tmp/tesslate-media-cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def cache_media(
        self,
        url: str,
        platform: str,
        media_type: str,
        auth_headers: dict[str, str] | None = None,
    ) -> str:
        """
        Download platform media to local cache.

        Returns local file path. Uses URL hash for deduplication.
        """
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        ext = _guess_extension(media_type)
        filename = f"{platform}_{url_hash}{ext}"
        filepath = self.cache_dir / filename

        if filepath.exists():
            return str(filepath)

        headers = auth_headers or {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            filepath.write_bytes(resp.content)

        logger.info("[MEDIA] Cached %s (%d bytes) → %s", platform, len(resp.content), filename)
        return str(filepath)

    async def transcribe_audio(self, audio_path: str) -> str:
        """
        Transcribe audio via LiteLLM (routes to OpenAI Whisper or compatible).

        Returns transcription text. Falls back to placeholder on error.
        """
        try:
            from ...config import get_settings

            settings = get_settings()

            if not settings.gateway_voice_transcription:
                return "[Voice message — transcription disabled]"

            # Use OpenAI-compatible Whisper API via LiteLLM
            import litellm

            response = await asyncio.to_thread(
                litellm.transcription,
                model=settings.gateway_voice_model,
                file=open(audio_path, "rb"),  # noqa: SIM115
            )
            text = response.text if hasattr(response, "text") else str(response)
            logger.info("[MEDIA] Transcribed %s → %d chars", audio_path, len(text))
            return text

        except ImportError:
            logger.warning("[MEDIA] litellm not available for transcription")
            return "[Voice message — transcription unavailable]"
        except Exception as e:
            logger.error("[MEDIA] Transcription failed for %s: %s", audio_path, e)
            return "[Voice message — transcription failed]"

    async def cleanup_cache(self, max_age_hours: int = 24) -> int:
        """Evict cached files older than max_age. Returns count deleted."""
        cutoff = time.time() - (max_age_hours * 3600)
        deleted = 0

        for filepath in self.cache_dir.iterdir():
            if filepath.is_file() and filepath.stat().st_mtime < cutoff:
                filepath.unlink(missing_ok=True)
                deleted += 1

        if deleted:
            logger.info("[MEDIA] Cleaned up %d cached files", deleted)
        return deleted


# Singleton instance
_pipeline: MediaPipeline | None = None


def get_media_pipeline() -> MediaPipeline:
    """Get or create the singleton MediaPipeline instance."""
    global _pipeline
    if _pipeline is None:
        from ...config import get_settings

        settings = get_settings()
        _pipeline = MediaPipeline(cache_dir=settings.gateway_media_cache_dir)
    return _pipeline


def _guess_extension(media_type: str) -> str:
    """Guess file extension from MIME type or media category."""
    mapping: dict[str, str] = {
        "audio": ".ogg",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/mp4": ".m4a",
        "image": ".jpg",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "application/pdf": ".pdf",
    }
    return mapping.get(media_type, ".bin")
