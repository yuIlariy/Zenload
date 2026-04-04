import os
import json
import asyncio
import logging
import random
import time
import aiohttp
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Instances API
INSTANCES_API = "https://instances.cobalt.best/api/instances.json"
INSTANCES_CACHE_TTL = 3600  # 1 hour

# Official API (requires token)
OFFICIAL_API = "https://api.cobalt.tools/"
OFFICIAL_TOKEN = os.getenv("COBALT_API_TOKEN", "")

# Fallback instances
FALLBACK_INSTANCES = [
    "https://cobalt-backend.canine.tools/",
    "https://cobalt-api.kwiatekmiki.com/",
    "https://capi.3kh0.net/",
    "https://cobalt-api.meowing.de/",
    "https://kityune.imput.net/",
    "https://nachos.imput.net/",
    "https://sunny.imput.net/",
    "https://blossom.imput.net/",
    "https://cobalt-7.kwiatekmiki.com/",
    "https://downloadapi.stuff.solutions/",
]

COBALT_SERVICES = {
    "instagram": ["instagram.com", "instagr.am"],
    "tiktok": ["tiktok.com", "vm.tiktok.com"],
    "twitter": ["twitter.com", "x.com", "t.co"],
    "youtube": ["youtube.com", "youtu.be", "music.youtube.com"],
    "reddit": ["reddit.com", "redd.it"],
    "pinterest": ["pinterest.com", "pin.it"],
    "snapchat": ["snapchat.com"],
    "twitch": ["twitch.tv", "clips.twitch.tv"],
    "vimeo": ["vimeo.com"],
    "soundcloud": ["soundcloud.com"],
    "facebook": ["facebook.com", "fb.watch"],
}

@dataclass
class CobaltResult:
    """Result from Cobalt API"""
    success: bool
    url: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    picker: Optional[list] = None

class CobaltService:
    """Universal Cobalt API client - FULLY ASYNC"""
    
    def __init__(self):
        self._instances: List[str] = []
        self._instances_updated: float = 0
        self._failed_instances: set = set()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30, connect=10),
                headers={'User-Agent': self._get_random_user_agent()}
            )
        return self._session

    def _get_random_user_agent(self) -> str:
        agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        return random.choice(agents)

    async def _fetch_instances(self) -> List[str]:
        """Fetch public instances using aiohttp"""
        session = await self._get_session()
        try:
            async with session.get(INSTANCES_API) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    instances = []
                    for item in data:
                        api = item.get('api') or item.get('api_url')
                        if api and item.get('trust', 0) >= 1:
                            if not api.startswith('http'): api = f"https://{api}"
                            if not api.endswith('/'): api += '/'
                            instances.append(api)
                    if instances: return instances
        except Exception as e:
            logger.debug(f"Failed to fetch instances: {e}")
        return FALLBACK_INSTANCES.copy()
    
    async def _get_instances(self) -> List[str]:
        now = time.time()
        if not self._instances or (now - self._instances_updated) > INSTANCES_CACHE_TTL:
            fetched = await self._fetch_instances()
            self._instances = list(set(fetched + FALLBACK_INSTANCES))
            self._instances_updated = now
            self._failed_instances.clear()
            random.shuffle(self._instances)
        
        available = [i for i in self._instances if i not in self._failed_instances]
        return available if available else self._instances

    async def _make_request(self, api_url: str, payload: dict, use_token: bool = False) -> Optional[dict]:
        """Make API request using aiohttp instead of curl"""
        session = await self._get_session()
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'Origin': api_url.rstrip("/"),
            'Referer': api_url,
        }
        
        if use_token and OFFICIAL_TOKEN:
            headers.update({
                'authorization': f'Bearer {OFFICIAL_TOKEN}',
                'origin': 'https://cobalt.tools',
                'referer': 'https://cobalt.tools/',
            })
        
        try:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status >= 400:
                    data = await resp.json()
                    return data # Return error data for status checking
        except Exception as e:
            logger.debug(f"Request to {api_url} failed: {e}")
        return None

    async def request(self, url: str, **kwargs) -> CobaltResult:
        """Main request logic"""
        payload = {
            "url": url,
            "videoQuality": kwargs.get("video_quality", "1080"),
            "audioFormat": kwargs.get("audio_format", "mp3"),
            "downloadMode": kwargs.get("download_mode", "auto"),
            "tiktokFullAudio": True,
        }
        
        # 1. Try Official API
        if OFFICIAL_TOKEN:
            data = await self._make_request(OFFICIAL_API, payload, use_token=True)
            if data and "status" in data:
                return self._parse_response(data)

        # 2. Try Fallbacks
        instances = await self._get_instances()
        for attempt, instance in enumerate(instances[:5]):
            logger.info(f"[Cobalt] Trying instance {attempt+1}: {instance}")
            data = await self._make_request(instance, payload)
            if data and "status" in data:
                res = self._parse_response(data)
                if res.success or res.error: return res
            self._failed_instances.add(instance)
        
        return CobaltResult(success=False, error="All instances failed")

    def _parse_response(self, data: dict) -> CobaltResult:
        status = data.get("status")
        if status in ("redirect", "tunnel"):
            return CobaltResult(success=True, url=data.get("url"), filename=data.get("filename"))
        elif status == "picker":
            return CobaltResult(success=True, picker=data.get("picker", []))
        elif status == "error":
            return CobaltResult(success=False, error=data.get("error", {}).get("code"))
        return CobaltResult(success=False, error="Unknown response")

    async def download(self, url: str, download_dir: Path, progress_callback=None, **kwargs) -> Tuple[Optional[str], Optional[Path]]:
        """Download file using aiohttp chunks for efficiency"""
        result = await self.request(url, **kwargs)
        if not result.success: return None, None
            
        target_url = result.url or (result.picker[0].get("url") if result.picker else None)
        if not target_url: return None, None
        
        if progress_callback: await progress_callback('status_downloading', 30)
        
        try:
            session = await self._get_session()
            async with session.get(target_url) as resp:
                if resp.status != 200: return None, None
                
                filename = result.filename or f"video_{int(time.time())}.mp4"
                file_path = download_dir / filename
                download_dir.mkdir(exist_ok=True)
                
                # Async writing
                with open(file_path, 'wb') as f:
                    f.write(await resp.read())
                
                if progress_callback: await progress_callback('status_downloading', 100)
                return filename, file_path
        except Exception as e:
            logger.error(f"[Cobalt] Download error: {e}")
            return None, None

    async def close(self):
        """Close the aiohttp session"""
        if self._session:
            await self._session.close()

    @staticmethod
    def can_handle(url: str) -> bool:
        return any(d in url.lower() for domains in COBALT_SERVICES.values() for d in domains)

cobalt = CobaltService()
