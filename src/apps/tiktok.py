from __future__ import annotations

import aiohttp
import re
from urllib.parse import urlparse, quote

from app_base import AppBase, ResolvedMedia

TIKTOK_HEADERS = {
	"User-Agent": (
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
		"AppleWebKit/537.36 (KHTML, like Gecko) "
		"Chrome/123.0.0.0 Safari/537.36"
	),
	"Accept-Language": "en-US,en;q=0.9",
}


class TikTokApp(AppBase):
	def __init__(self):
		super().__init__(TIKTOK_HEADERS)

	URL_REGEX = re.compile(r"https?://\S+")
	TIKTOK_DOMAINS = {"tiktok.com", "www.tiktok.com", "vm.tiktok.com", "m.tiktok.com"}

	def match(self, message_content: str) -> str | None:
		for m in self.URL_REGEX.finditer(message_content):
			candidate = m.group(0).strip("<>").rstrip(").,")
			if self.is_link(candidate):
				return candidate
		return None

	def is_link(self, url: str) -> bool:
		domain = urlparse(url).netloc.lower()
		return any(domain == d or domain.endswith("." + d) for d in self.TIKTOK_DOMAINS)

	async def resolve(self, url: str):
		if not self.is_link(url):
			raise ValueError("Invalid link source. Only tiktok.com links are allowed.")

		try:
			api_url = f"https://www.tikwm.com/api/?url={quote(url, safe='')}"

			async with aiohttp.ClientSession() as session:
				async with session.get(api_url, headers=TIKTOK_HEADERS) as response:
					if response.status != 200:
						raise RuntimeError(f"TikTok API returned HTTP {response.status}")
					data = await response.json(content_type=None)

			if data.get("code") != 0:
				raise RuntimeError(data.get("msg", "Unknown API error"))

			video_data = data.get("data", {})

			# Photo slideshow posts
			images = video_data.get("images")
			if images:
				return [ResolvedMedia(url=img.get("url", img), is_video=False)
						for img in images if (img.get("url") if isinstance(img, dict) else img)]

			# Video posts — prefer no-watermark
			play_url = video_data.get("play") or video_data.get("wmplay")
			if play_url:
				return [ResolvedMedia(url=play_url, is_video=True)]

			raise RuntimeError("No video or images found in API response")
		except Exception as exc:
			return f"Error processing the TikTok link: {exc}"
