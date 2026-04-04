import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "youtube.txt"

    def platform_id(self) -> str:
        return 'youtube'

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.netloc and any(domain in parsed.netloc.lower() for domain in ['youtube.com', 'www.youtube.com', 'youtu.be']))

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'
        return url

    async def get_formats(self, url: str) -> List[Dict]:
        """Get formats with JS challenge support enabled"""
        try:
            self.update_progress('status_getting_info', 0)
            processed_url = self.preprocess_url(url)
            
            # Options matched to your successful terminal test
            extract_opts = {
                'format': 'bestvideo+bestaudio/best',
                'quiet': True,
                'no_warnings': False, # Enabled to see JS issues in logs
                'noplaylist': True,
                # Explicitly allow remote components to help solve n-challenges
                'allow_unsecure_scripts': True, 
            }
            if self.cookie_file.exists():
                extract_opts['cookiefile'] = str(self.cookie_file)
            
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, str(processed_url), download=False)
                
                if info and 'formats' in info:
                    formats = []
                    seen = set()
                    for f in info['formats']:
                        # Skip storyboard 'sb' formats and audio-only
                        if f.get('height') and f.get('vcodec') != 'none' and 'storyboard' not in f.get('format_note', '').lower():
                            quality = f"{f['height']}p"
                            if quality not in seen:
                                formats.append({
                                    'id': f['format_id'],
                                    'quality': quality,
                                    'ext': f['ext']
                                })
                                seen.add(quality)
                    
                    if not formats:
                        raise DownloadError("No valid video formats found.")
                        
                    return sorted(formats, key=lambda x: int(x['quality'][:-1]), reverse=True)
            
            raise DownloadError("YouTube manifest extraction failed.")

        except Exception as e:
            logger.error(f"[YouTube] Extraction failed: {e}")
            raise DownloadError(f"Extraction error: {str(e)}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download phase using the solved JS signatures"""
        try:
            self.update_progress('status_downloading', 0)
            processed_url = self.preprocess_url(url)
            download_dir = (Path(__file__).parent.parent.parent / "downloads").resolve()
            download_dir.mkdir(exist_ok=True)

            ydl_opts = {
                # Force standard mp4 merging as per your terminal successful formats
                'format': f"{format_id}+bestaudio[ext=m4a]/best" if format_id else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                'merge_output_format': 'mp4',
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'progress_hooks': [self._progress_hook],
                'noplaylist': True,
            }
            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, str(processed_url), download=True)
                file_path = Path(ydl.prepare_filename(info)).resolve()
                
                if file_path.exists():
                    return self._prepare_metadata(info, processed_url), file_path

            raise DownloadError("File verification failed after download.")

        except Exception as e:
            logger.error(f"[YouTube] Download failed: {e}")
            raise DownloadError(f"Download error: {str(e)}")

    def _prepare_metadata(self, info: Dict, url: str) -> str:
        views = info.get('view_count', 0)
        channel = info.get('uploader', 'Unknown')
        return f"⚡YouTube | {views:,} Views\n\n✨By {channel}\n\n📥Downloaded via: @Tik_TokDownloader_Bot"

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading':
            try:
                loop = asyncio.get_event_loop()
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 70) + 20
                    asyncio.run_coroutine_threadsafe(self.update_progress('status_downloading', progress), loop)
            except: pass
