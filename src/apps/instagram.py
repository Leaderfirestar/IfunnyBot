import aiohttp
import json
import re
from urllib.parse import urlparse
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse, urlunparse
from bs4 import BeautifulSoup
from yarl import URL
from apps.app_base import AppBase

INSTAGRAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

class InstagramApp(AppBase):
	def __init__(self):
		super().__init__(INSTAGRAM_HEADERS)

	INSTAGRAM_GRAPHQL_DOC_ID = "8845758582119845"
	INSTAGRAM_GRAPHQL_APP_ID = "936619743392459"
	LSD_PATTERNS = [
		re.compile(r'"LSD",\[\],{"token":"([^"]+)'),
		re.compile(r'"LSD":{"token":"([^"]+)'),
		re.compile(r'"lsd",\[\],{"token":"([^"]+)'),
	]
	URL_REGEX = re.compile(r"https?://\S+")

	def match(self, message_content: str) -> str | None:
		for match in self.URL_REGEX.finditer(message_content):
			candidate = match.group(0).strip("<>")
			candidate = candidate.rstrip(").,")
			if self.is_link(candidate):
				return candidate
		return None
	
	def is_link(self, url: str) -> bool:
		parsed_url = urlparse(url)
		domain = parsed_url.netloc.lower()
		return domain.endswith("instagram.com") or domain.endswith("instagr.am")

	async def resolve(self, url: str):
		if not self.is_link(url):
			raise ValueError("⚠️ Invalid link source. Only instagram.com links are allowed.")
		try:
			query_params = parse_qs(urlparse(url).query)
			async with aiohttp.ClientSession(headers=INSTAGRAM_HEADERS) as session:
				try:
					async with session.get(url) as response:
						if response.status != 200:
							raise RuntimeError(f"Failed to fetch Instagram page: {response.status}")
						html = await response.text()
				except aiohttp.ClientError as exc:
					raise RuntimeError(f"Failed to fetch Instagram page: {exc}") from exc

				soup = BeautifulSoup(html, "html.parser")
				media_items = self.extract_instagram_media_from_meta(soup)
				lsd_token = None

				if media_items and not (query_params.get("img_index") or query_params.get("img_index[]")):
					return media_items

				for pattern in self.LSD_PATTERNS:
					match = pattern.search(html)
					if match:
						lsd_token = match.group(1)
						break

				return await self._resolve_instagram_via_graphql(session, url, lsd_token)
		except Exception as exc:
			return f"Error processing the Instagram link: {exc}"

		
	def extract_instagram_media_from_meta(self, soup: BeautifulSoup) -> list[ResolvedMedia]:
		meta = self._collect_meta(soup)

		for key in ("og:video:secure_url", "og:video:url", "og:video"):
			candidate = meta.get(key)
			if candidate:
				return [ResolvedMedia(url=candidate, is_video=True)]

		image = meta.get("og:image")
		if image:
			return [ResolvedMedia(url=image, is_video=False)]

		return []
	
	def _collect_meta(self, soup: BeautifulSoup) -> dict[str, str]:
		meta: dict[str, str] = {}
		for tag in soup.find_all("meta"):
			key = tag.get("property") or tag.get("name")
			value = tag.get("content")
			if key and value:
				meta[key.lower()] = value
		return meta
	
	async def _resolve_instagram_via_graphql(self, session: aiohttp.ClientSession, instagram_link: str, lsd_token: str | None) -> list[ResolvedMedia]:
		shortcode, canonical_path, query_params = self._extract_instagram_shortcode(instagram_link)

		variables = {
			"shortcode": shortcode,
			"fetch_comment_count": 0,
			"parent_comment_count": 0,
			"child_comment_count": 0,
			"has_threaded_comments": False,
			"hoisted_comment_id": "",
			"hoisted_reply_id": "",
		}

		cookies = session.cookie_jar.filter_cookies(URL("https://www.instagram.com/"))
		csrf_cookie = cookies.get("csrftoken")
		lsd_cookie = cookies.get("lsd")

		graphql_headers = {
			**INSTAGRAM_HEADERS,
			"Accept": "*/*",
			"X-IG-App-ID": self.INSTAGRAM_GRAPHQL_APP_ID,
			"Referer": urlunparse(("https", "www.instagram.com", f"/{canonical_path}", "", "", "")),
			"X-ASBD-ID": "129477",
			"X-Requested-With": "XMLHttpRequest",
		}

		if csrf_cookie:
			graphql_headers["X-CSRFToken"] = csrf_cookie.value
		if lsd_cookie:
			graphql_headers["X-FB-LSD"] = lsd_cookie.value
		elif lsd_token:
			graphql_headers["X-FB-LSD"] = lsd_token

		params = {
			"doc_id": self.INSTAGRAM_GRAPHQL_DOC_ID,
			"variables": json.dumps(variables, separators=(",", ":")),
		}

		try:
			async with session.get(
				"https://www.instagram.com/graphql/query/", params=params, headers=graphql_headers
			) as response:
				if response.status != 200:
					raise RuntimeError(f"Instagram GraphQL returned HTTP {response.status}")
				payload = await response.json(content_type=None)
		except aiohttp.ClientError as exc:
			raise RuntimeError(f"GraphQL request failed: {exc}") from exc

		try:
			media = payload["data"]["xdt_shortcode_media"]
		except (KeyError, TypeError) as exc:
			raise RuntimeError("Unexpected GraphQL response structure") from exc

		if not media:
			raise RuntimeError("GraphQL response did not include media information")

		if media.get("is_video") and media.get("video_url"):
			return [ResolvedMedia(url=media["video_url"], is_video=True)]

		if media.get("__typename") == "XDTGraphSidecar":
			edges = media.get("edge_sidecar_to_children", {}).get("edges") or []
			items: list[ResolvedMedia] = []
			for edge in edges:
				node = edge.get("node", {})
				resolved = self._media_from_graph_node(node)
				if resolved:
					items.append(resolved)
			if items:
				index_values = query_params.get("img_index") or query_params.get("img_index[]")
				if index_values:
					try:
						raw_index = int(index_values[0])
					except (TypeError, ValueError):
						raw_index = 1

					idx = max(0, min(len(items) - 1, raw_index - 1))
					return [items[idx]]

				return items

		display_url = media.get("display_url")
		if display_url:
			return [ResolvedMedia(url=display_url, is_video=False)]

		raise RuntimeError("GraphQL response missing media URLs")
	
	def _extract_instagram_shortcode(self, instagram_link: str) -> tuple[str, str, dict[str, list[str]]]:
		parsed = urlparse(instagram_link)
		path_segments = [segment for segment in parsed.path.split("/") if segment]
		if len(path_segments) < 2:
			raise ValueError("Unrecognized Instagram URL format; expected /<type>/<shortcode>/")
		shortcode = path_segments[1]
		canonical_path = "/".join(path_segments[:2]) + "/"
		query_params = parse_qs(parsed.query)
		return shortcode, canonical_path, query_params
	
	def _media_from_graph_node(self, node: dict) -> ResolvedMedia | None:
		if node.get("is_video") and node.get("video_url"):
			return ResolvedMedia(url=node["video_url"], is_video=True)

		if node.get("is_video") and node.get("video_resources"):
			resources = node["video_resources"]
			if isinstance(resources, list) and resources:
				best = max(resources, key=lambda r: r.get("width", 0))
				src = best.get("src")
				if src:
					return ResolvedMedia(url=src, is_video=True)

		display_url = node.get("display_url")
		if display_url:
			return ResolvedMedia(url=display_url, is_video=False)

		return None
		
@dataclass
class ResolvedMedia:
    url: str
    is_video: bool | None = None