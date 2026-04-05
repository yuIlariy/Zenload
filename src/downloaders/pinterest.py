"""Pinterest downloader - Cobalt primary, yt-dlp fallback"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)


class PinterestDownloader(BaseDownloader):
    """Pinterest downloader using Cobalt API with yt-dlp fallback"""
    
    def __init__(self):
        super().__init__()

    def platform_id(self) -> str:
        return 'pinterest'

    def can_handle(self, url: str) -> bool:
        return any(x in url.lower() for x in ['pinterest.com', 'pin.it'])

    async def get_formats(self, url: str) -> List[Dict]:
        """Return safe formats only (avoid broken Pinterest formats)"""
        self.update_progress('status_getting_info', 0)

        # Try Cobalt first
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Auto', 'ext': 'mp4'}]

        # Fallback → DO NOT expose raw yt-dlp formats (causes errors)
        logger.info(f"[Pinterest] Cobalt failed ({result.error}), using safe fallback")
        self.update_progress('status_getting_info', 100)
        return [{'id': 'best', 'quality': 'Auto', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, yt-dlp fallback"""
        logger.info(f"[Pinterest] Downloading: {url}")

        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)

        # === Metadata (safe prefetch) ===
        title = "Pinterest Video"
        uploader = "Pinterest"

        try:
            def get_info():
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await asyncio.to_thread(get_info)
            title = info.get('title') or info.get('description') or title
            uploader = info.get('uploader') or info.get('channel') or uploader
        except Exception:
            pass

        if len(title) > 800:
            title = title[:797] + "..."

        caption = (
            f"🎬 <b>{title}</b>\n\n"
            f"⚡ Pinterest\n"
            f"✨ By {uploader}\n\n"
            f"📥 Downloader: @Tik_TokDownloader_Bot"
        )

        # === TRY COBALT ===
        self.update_progress('status_downloading', 10)

        try:
            filename, file_path = await cobalt.download(
                url,
                download_dir,
                progress_callback=self.update_progress
            )

            if file_path and file_path.exists() and file_path.stat().st_size > 0:
                return caption, file_path

        except Exception as e:
            logger.warning(f"[Pinterest] Cobalt failed: {e}")

        # === FALLBACK → yt-dlp (HARDENED) ===
        logger.info("[Pinterest] Falling back to yt-dlp")
        self.update_progress('status_downloading', 30)

        try:
            ydl_opts = {
                'format': 'bv*+ba/b',  # best video+audio or fallback
                'merge_output_format': 'mp4',
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'quiet': True,
                'noplaylist': True,
                'retries': 3,
                'fragment_retries': 3,
                'nocheckcertificate': True,
            }

            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    file_path = Path(ydl.prepare_filename(info)).resolve()

                    # Fix extension mismatch after merge
                    if not file_path.exists():
                        alt = file_path.with_suffix(".mp4")
                        if alt.exists():
                            file_path = alt

                    return info, file_path

            info, file_path = await asyncio.wait_for(
                asyncio.to_thread(download_video),
                timeout=60
            )

            if file_path and file_path.exists():
                title = info.get('title') or title
                if len(title) > 800:
                    title = title[:797] + "..."

                final_caption = (
                    f"🎬 <b>{title}</b>\n\n"
                    f"⚡ Pinterest\n"
                    f"✨ By {uploader}\n\n"
                    f"📥 Downloader: @Tik_TokDownloader_Bot"
                )

                return final_caption, file_path

            raise DownloadError("File not found after download")

        except Exception as e:
            logger.error(f"[Pinterest] Download failed: {e}")
            raise DownloadError(f"Download failed: {str(e)}")
