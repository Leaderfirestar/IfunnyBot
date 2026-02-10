from __future__ import annotations

import os
import io
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass
import aiohttp
import discord
from abc import ABC, abstractmethod


@dataclass
class ResolvedMedia:
	url: str
	is_video: bool | None = None


def _has_heic_filename(filename: str) -> bool:
	return os.path.splitext(filename)[1].lower() in (".heic", ".heif")


def _is_real_heic(data: bytes, content_type: str = "") -> bool:
	ct = content_type.lower()
	if "heic" in ct or "heif" in ct:
		return True
	if len(data) >= 12 and data[4:8] == b"ftyp":
		brand = data[8:12]
		if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
			return True
	return False


def _fix_heic_media(data: bytes, filename: str, content_type: str = "") -> tuple[bytes, str]:
	base = os.path.splitext(filename)[0]
	new_filename = base + ".jpg"

	# If data is already JPEG/PNG (Instagram CDN converts via stp=dst-jpg),
	# just fix the filename so Discord embeds it properly.
	if data[:3] == b"\xff\xd8\xff":
		return data, new_filename
	if data[:8] == b"\x89PNG\r\n\x1a\n":
		return data, base + ".png"

	# Actual HEIC data — transcode to JPEG
	from PIL import Image
	import pillow_heif

	pillow_heif.register_heif_opener()

	img = Image.open(io.BytesIO(data))
	if img.mode in ("RGBA", "P"):
		img = img.convert("RGB")

	output = io.BytesIO()
	img.save(output, format="JPEG", quality=95)

	return output.getvalue(), new_filename


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
					content_type = media_response.headers.get("Content-Type", "")

			if len(media_bytes) > self.MAX_DISCORD_FILE_SIZE:
				await message.channel.send(media_url)
				return

			filename = self.filename_from_url(media_url, is_video)

			if not is_video and (_is_real_heic(media_bytes, content_type) or _has_heic_filename(filename)):
				media_bytes, filename = _fix_heic_media(media_bytes, filename, content_type)

			await message.channel.send(file=discord.File(io.BytesIO(media_bytes), filename=filename))
		except Exception as exc:
			await message.channel.send(f"Failed to deliver media: {exc}")

	def filename_from_url(self, url: str, is_video: bool | None = None) -> str:
		path = urlsplit(url).path
		name = path.rsplit("/", 1)[-1] or "media"
		if not os.path.splitext(name)[1] and is_video is not None:
			name += ".mp4" if is_video else ".jpg"
		return name