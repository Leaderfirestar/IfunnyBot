import os
import io
from urllib.parse import urljoin, urlsplit
import aiohttp
import discord
from abc import ABC, abstractmethod

class AppBase(ABC):
	"""Abstract base class for all media apps (e.g., iFunny, Instagram)."""

	def __init__(self, headers: dict[str, str]):
		self.headers = headers

	candidate_urls: list[str] = []
	MAX_DISCORD_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

	@abstractmethod
	def match(self, message_content: str) -> str | None:
		"""Return a matching URL if this app should handle the message."""
		pass

	@abstractmethod
	async def resolve(self, url: str):
		"""Return one or more media URLs (or ResolvedMedia objects)."""
		pass
	
	@abstractmethod
	def is_link(self, url: str) -> bool:
		"""Check if the URL belongs to this app."""
		pass

	def _add_candidate(self, url: str, base_url: str) -> None:
		if not url:
			return
		url = url.strip()
		if url.startswith("//"):
			url = f"https:{url}"
		elif url.startswith("/"):
			url = urljoin(base_url, url)
		if not url.lower().startswith("http"):
			return
		if url not in self.candidate_urls:
			self.candidate_urls.append(url)

	async def handle_message(self, message: discord.Message, url: str):
		"""Fetch, resolve, and deliver media."""
		try:
			media_items = await self.resolve(url)
		except Exception as exc:
			await message.channel.send(f"Error processing the link: {exc}")
			return

		if not media_items:
			await message.channel.send("Could not find media in the link.")
			return

		if isinstance(media_items, str):
			await self.deliver_media(message, media_items, self.headers)
		else:
			for item in media_items:
				await self.deliver_media(
					message,
					item.url if hasattr(item, "url") else item,
					self.headers,
					getattr(item, "is_video", None),
				)

	async def deliver_media(self, message: discord.Message, media_url: str, headers: dict[str, str], is_video: bool | None = None) -> None:
		try:
			async with aiohttp.ClientSession(headers=headers) as session:
				async with session.get(media_url) as media_response:
					if media_response.status != 200:
						await message.channel.send("Failed to download media.")
						return

					size_header = media_response.headers.get("Content-Length")
					if size_header and int(size_header) > self.MAX_DISCORD_FILE_SIZE:
						await message.channel.send(media_url)
						return

					media_bytes = await media_response.read()

			if len(media_bytes) > self.MAX_DISCORD_FILE_SIZE:
				await message.channel.send(media_url)
				return

			filename = self.filename_from_url(media_url, is_video)
			await message.channel.send(file=discord.File(io.BytesIO(media_bytes), filename=filename))
		except Exception as exc:
			await message.channel.send(f"Failed to deliver media: {exc}")

	def filename_from_url(self, url: str, is_video: bool | None = None) -> str:
		path = urlsplit(url).path
		name = path.rsplit("/", 1)[-1] or "media"
		if not os.path.splitext(name)[1] and is_video is not None:
			name += ".mp4" if is_video else ".jpg"
		return name