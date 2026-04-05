import os
import re
import logging
import asyncio
from pathlib import Path
from typing import Tuple, Dict, List, Optional
import requests
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..config import DOWNLOADS_DIR

logger = logging.getLogger(__name__)

class YandexMusicDownloader(BaseDownloader):
    """Downloader for Yandex Music with professional metadata formatting"""

    def __init__(self):
        super().__init__()
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize Yandex Music client"""
        try:
            from yandex_music import Client
            token = os.getenv('YANDEX_MUSIC_TOKEN')
            if not token:
                logger.info("YANDEX_MUSIC_TOKEN not found, will use YouTube fallback")
                return
            
            try:
                self.client = Client(token).init()
                logger.info("Yandex Music client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Yandex Music client: {e}")
                self.client = None
        except ImportError:
            logger.warning("yandex_music library not installed, will use YouTube fallback")

    def platform_id(self) -> str:
        return "yandex_music"

    def can_handle(self, url: str) -> bool:
        """Check if URL is from Yandex Music"""
        patterns = [
            r'music\.yandex\.[a-z]+/album/(\d+)/track/(\d+)',
            r'music\.yandex\.[a-z]+/track/(\d+)',
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def _extract_track_id(self, url: str) -> str:
        """Extract track ID from URL"""
        match = re.search(r'album/(\d+)/track/(\d+)', url)
        if match:
            return f"{match.group(2)}:{match.group(1)}"
        
        match = re.search(r'track/(\d+)', url)
        if match:
            return match.group(1)
        
        raise DownloadError("Could not extract track ID from URL")

    async def _get_track_info_from_page(self, url: str) -> Optional[Dict]:
        """Get track info by fetching Yandex Music page HTML (no auth required)"""
        logger.info(f"[Yandex] Fetching track info from page: {url}")
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=15)
            if response.status_code != 200:
                return None
            
            html = response.text
            title, artist = None, None
            
            og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og_title:
                title = og_title.group(1)
            
            og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
            if og_desc:
                desc = og_desc.group(1)
                parts = desc.split('•')
                if parts:
                    artist = parts[0].strip()
            
            if title and artist:
                return {'search_query': f"{artist} - {title}", 'title': title, 'artist': artist}
            elif title:
                return {'search_query': title, 'title': title, 'artist': 'Unknown Artist'}
            
            return None
        except Exception as e:
            logger.error(f"[Yandex] Failed to fetch page: {e}")
            return None

    async def _get_track_info_from_api(self, track_id: str) -> Optional[Dict]:
        """Get track info from Yandex Music API (requires token)"""
        if not self.client:
            return None
        try:
            track = self.client.tracks([track_id])[0]
            if track:
                return {
                    'title': track.title,
                    'artists': ", ".join(artist.name for artist in track.artists),
                    'track': track
                }
        except Exception as e:
            logger.error(f"Failed to get track info from API: {e}")
        return None

    async def _download_from_youtube(self, query: str, original_title: str = None, original_artist: str = None) -> Optional[Tuple[str, Path]]:
        """Download audio from YouTube search with professional caption"""
        logger.info(f"[Yandex] Downloading from YouTube: {query}")
        
        safe_filename = self._prepare_filename(query)
        file_path = DOWNLOADS_DIR / f"{safe_filename}.mp3"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(DOWNLOADS_DIR / f"{safe_filename}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'nooverwrites': True,
            'quiet': True,
            'progress_hooks': [self._progress_hook],
            'default_search': 'ytsearch1',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_progress('status_downloading', 40)
                info = await asyncio.to_thread(ydl.extract_info, f"ytsearch1:{query}", download=True)
                
                if info:
                    entry = info['entries'][0] if 'entries' in info else info
                    
                    # Use original metadata if we have it, otherwise YouTube's
                    display_title = original_title or entry.get('title', query)
                    display_artist = original_artist or entry.get('uploader', 'Unknown')

                    # 🔥 Safety Truncation
                    if len(display_title) > 800:
                        display_title = display_title[:797] + "..."

                    # 🔥 Professional Caption
                    metadata = (
                        f"🎬 <b>{display_title}</b>\n\n"
                        f"🎧 Yandex Music | YouTube Fallback\n"
                        f"✨ By {display_artist}\n\n"
                        f"📥 Downloader: @Tik_TokDownloader_Bot"
                    )
                    
                    if file_path.exists():
                        return metadata, file_path
                    
                    actual_filename = ydl.prepare_filename(entry)
                    actual_path = Path(actual_filename).with_suffix('.mp3')
                    if actual_path.exists():
                        return metadata, actual_path
        except Exception as e:
            logger.error(f"[Yandex] YouTube download failed: {e}")
        return None

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'mp3', 'quality': 'MP3 320kbps', 'ext': 'mp3'}]

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        """Download track from Yandex Music or YouTube fallback"""
        try:
            self.update_progress('status_downloading', 0)
            track_id = self._extract_track_id(url)

            # --- Try Yandex Music API First ---
            if self.client:
                try:
                    track_info = await self._get_track_info_from_api(track_id)
                    if track_info and track_info.get('track'):
                        track = track_info['track']
                        artists = track_info['artists']
                        
                        title_safe = self._prepare_filename(track.title)
                        filename = f"{artists} - {title_safe}.mp3"
                        file_path = DOWNLOADS_DIR / filename

                        self.update_progress('status_downloading', 60)
                        await asyncio.to_thread(track.download, str(file_path))
                        self.update_progress('status_downloading', 100)

                        # 🔥 Professional Caption for Native API
                        display_title = track.title
                        if len(display_title) > 800:
                            display_title = display_title[:797] + "..."

                        metadata = (
                            f"🎬 <b>{display_title}</b>\n\n"
                            f"🎧 Yandex Music\n"
                            f"✨ By {artists}\n\n"
                            f"📥 Downloader: @Tik_TokDownloader_Bot"
                        )
                        return metadata, file_path
                except Exception as e:
                    logger.info(f"[Yandex] API path failed: {e}")

            # --- YouTube Fallback Path ---
            self.update_progress('status_downloading', 20)
            page_info = await self._get_track_info_from_page(url.split('?')[0])
            
            if not page_info:
                raise DownloadError("Failed to fetch track info")

            result = await self._download_from_youtube(
                page_info['search_query'], 
                original_title=page_info.get('title'),
                original_artist=page_info.get('artist')
            )
            
            if result:
                self.update_progress('status_downloading', 100)
                return result

            raise DownloadError("Download failed via all providers")

        except Exception as e:
            logger.error(f"[Yandex] Error: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")

    def _progress_hook(self, d: Dict):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 60) + 30
                    self.update_progress('status_downloading', progress)
            except:
                pass
