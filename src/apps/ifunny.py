import aiohttp
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from app_base import AppBase

IFUNNY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ifunny.co/",
    "Connection": "keep-alive",
}

class IFunnyApp(AppBase):
	def __init__(self):
		super().__init__(IFUNNY_HEADERS)

	def match(self, message_content: str) -> str | None:
		if message_content.startswith("Tap to see the meme -"):
			return message_content.split("Tap to see the meme -", 1)[1].strip()
		return None
	
	def is_link(self, url: str) -> bool:
		parsed_url = urlparse(url)
		return parsed_url.netloc.lower().endswith("ifunny.co")

	async def resolve(self, url: str):
		if not self.is_ifunny_link(url):
			return "⚠️ Invalid link source. Only ifunny.co links are allowed."

		try:
			async with aiohttp.ClientSession(headers=IFUNNY_HEADERS) as session:
				async with session.get(url) as response:
					if response.status != 200:
						raise RuntimeError(f"Failed to fetch meme page: {response.status}")
					html = await response.text()

				self.extract_ifunny_media_urls(html, url)

				media_url = await self.choose_preferred_media_url(session, self.candidate_urls)

				if not media_url:
					raise ValueError("Could not find meme in the link.")

				return media_url
		except Exception as exc:
			return f"Error processing the link: {exc}"
	
	def extract_ifunny_media_urls(self, html: str, base_url: str) -> None:
		soup = BeautifulSoup(html, "html.parser")

		image_tag = soup.find("meta", property="og:image")
		video_tag = soup.find("meta", property="og:video:secure_url")

		if video_tag:
			self._add_candidate(video_tag.get("content"), base_url)
		if image_tag:
			self._add_candidate(image_tag.get("content"), base_url)

		for tag in soup.find_all(["source", "video", "img"]):
			for attr in ("src", "data-src", "data-gif", "data-original", "data-url"):
				self._add_candidate(tag.get(attr), base_url)

	async def choose_preferred_media_url(self, session: aiohttp.ClientSession, candidate_urls: list[str]) -> str | None:
		if not candidate_urls:
			return None

		for url in candidate_urls:
			if url.lower().endswith(".gif"):
				return url

		for url in candidate_urls:
			lower = url.lower()
			if lower.endswith(".mp4"):
				gif_candidate = url[:-4] + ".gif"
				if await self._url_exists(session, gif_candidate):
					return gif_candidate

		for ext in (".mp4", ".webm"):
			for url in candidate_urls:
				if url.lower().endswith(ext):
					return url

		return candidate_urls[0]
	
	async def _url_exists(self, session: aiohttp.ClientSession, url: str) -> bool:
		try:
			async with session.head(url) as response:
				if response.status == 200:
					return True
				if response.status in (403, 405):
					async with session.get(url, headers={"Range": "bytes=0-0"}) as probe:
						return probe.status == 200
		except aiohttp.ClientError:
			return False
		return False