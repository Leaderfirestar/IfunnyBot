import os
import re
from urllib.parse import urlparse
from xdk import Client
from apps.app_base import AppBase

TWITTER_HEADERS = {
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

class TwitterApp(AppBase):
	def __init__(self):
		super().__init__(TWITTER_HEADERS)

	_x = Client(bearer_token=os.getenv("X_TOKEN"))

	def match(self, message_content: str) -> str | None:
		return message_content if self.is_link(message_content) else None

	def is_link(self, url: str) -> bool:
		url = urlparse(url)
		return "twitter.com" in url.netloc or "x.com" in url.netloc

	async def resolve(self, url: str):
		if not self.is_link(url):
			raise ValueError("⚠️ Invalid link source. Only twitter/x.com links are allowed.")
		medias = self.extract_twitter_medias(url)

		if len(medias) == 0:
			raise ValueError("Could not find media in the link.")

		return medias

	def extract_twitter_medias(self, base_url: str) -> list[str] | None:
		tweet_id = self.get_tweet_id(base_url)
		medias = self.fetch_media(tweet_id)
		return medias

	def get_tweet_id(self, url: str) -> str | None:
		match = re.search(r"status/(\d+)", url)
		if not match:
			raise ValueError("Invalid Twitter URL format.")
		return match.group(1)

	def fetch_media(self, tweet_id: str) -> str | None:
		post = dict(self._x.posts.get_by_id(tweet_id, expansions=["attachments.media_keys"], mediafields=["url", "type", "variants"]))
		medias = post["includes"]["media"]
		final_medias = []
		for media in medias:
			variants = media["variants"]
			sorted_variants = sorted(variants, key=lambda x: x.get("bit_rate", 0), reverse=True)
			highest_bitrate_variant = sorted_variants[0]
			final_medias.append(highest_bitrate_variant["url"])
		return final_medias