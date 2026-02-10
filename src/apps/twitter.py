from __future__ import annotations

import aiohttp
import re
from urllib.parse import urlparse

from app_base import AppBase, ResolvedMedia

TWITTER_HEADERS = {
	"User-Agent": (
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
		"AppleWebKit/537.36 (KHTML, like Gecko) "
		"Chrome/123.0.0.0 Safari/537.36"
	),
	"Accept-Language": "en-US,en;q=0.9",
}


class TwitterApp(AppBase):
	def __init__(self):
		super().__init__(TWITTER_HEADERS)

	URL_REGEX = re.compile(r"https?://\S+")
	TWITTER_DOMAINS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
	SHORTLINK_DOMAINS = {"t.co", "www.t.co"}

	def match(self, message_content: str) -> str | None:
		for m in self.URL_REGEX.finditer(message_content):
			candidate = m.group(0).strip("<>").rstrip(").,")
			if self.is_link(candidate):
				return candidate
		return None

	def is_link(self, url: str) -> bool:
		domain = urlparse(url).netloc.lower()
		return domain in self.TWITTER_DOMAINS or domain in self.SHORTLINK_DOMAINS

	async def resolve(self, url: str):
		if not self.is_link(url):
			raise ValueError("Invalid link source. Only twitter.com/x.com links are allowed.")

		try:
			parsed = urlparse(url)

			# For t.co short links, follow redirect to get the real URL
			if parsed.netloc.lower() in self.SHORTLINK_DOMAINS:
				async with aiohttp.ClientSession() as session:
					async with session.get(url, allow_redirects=True) as resp:
						url = str(resp.url)
						parsed = urlparse(url)
						if parsed.netloc.lower() not in self.TWITTER_DOMAINS:
							raise RuntimeError("Short link did not resolve to a Twitter/X URL")

			api_url = f"https://api.fxtwitter.com{parsed.path}"

			async with aiohttp.ClientSession() as session:
				async with session.get(api_url) as response:
					if response.status != 200:
						raise RuntimeError(f"fxtwitter API returned HTTP {response.status}")
					data = await response.json(content_type=None)

			tweet = data.get("tweet")
			if not tweet:
				raise RuntimeError("No tweet data found")

			media = tweet.get("media")
			if not media:
				raise RuntimeError("No media found in tweet")

			all_media = media.get("all") or media.get("photos") or media.get("videos") or []
			if not all_media:
				raise RuntimeError("No media items found in tweet")

			items = []
			for m in all_media:
				media_type = m.get("type", "")
				if media_type in ("video", "gif"):
					media_url = m.get("url")
					if media_url:
						items.append(ResolvedMedia(url=media_url, is_video=True))
				elif media_type == "photo":
					media_url = m.get("url")
					if media_url:
						items.append(ResolvedMedia(url=media_url, is_video=False))

			if not items:
				raise RuntimeError("Could not extract media URLs from tweet")

			return items
		except Exception as exc:
			return f"Error processing the Twitter link: {exc}"
