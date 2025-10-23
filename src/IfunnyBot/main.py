import argparse
import asyncio
import io
import json
import os
import re
import sys
from dataclasses import dataclass

import aiohttp
import discord
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from collections.abc import Callable
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit, urlunparse
from yarl import URL
from yarl import URL

IFUNNY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ifunny.co/",
    "Connection": "keep-alive",
}

INSTAGRAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

INSTAGRAM_GRAPHQL_DOC_ID = "8845758582119845"
INSTAGRAM_GRAPHQL_APP_ID = "936619743392459"

MAX_DISCORD_FILE_SIZE = 8 * 1024 * 1024  # 8 MB
URL_REGEX = re.compile(r"https?://\S+")
LSD_PATTERNS = [
    re.compile(r'"LSD",\[\],{"token":"([^"]+)'),
    re.compile(r'"LSD":{"token":"([^"]+)'),
    re.compile(r'"lsd",\[\],{"token":"([^"]+)'),
]

load_dotenv()


@dataclass
class ResolvedMedia:
    url: str
    is_video: bool | None = None


def is_ifunny_link(url: str) -> bool:
    parsed_url = urlparse(url)
    return parsed_url.netloc.lower().endswith("ifunny.co")


def is_instagram_link(url: str) -> bool:
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    return domain.endswith("instagram.com") or domain.endswith("instagr.am")


def _add_candidate(url: str, base_url: str, collector: list[str]) -> None:
    if not url:
        return
    url = url.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = urljoin(base_url, url)
    if not url.lower().startswith("http"):
        return
    if url not in collector:
        collector.append(url)


def extract_ifunny_media_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidate_urls: list[str] = []

    image_tag = soup.find("meta", property="og:image")
    video_tag = soup.find("meta", property="og:video:secure_url")

    if video_tag:
        _add_candidate(video_tag.get("content"), base_url, candidate_urls)
    if image_tag:
        _add_candidate(image_tag.get("content"), base_url, candidate_urls)

    for tag in soup.find_all(["source", "video", "img"]):
        for attr in ("src", "data-src", "data-gif", "data-original", "data-url"):
            _add_candidate(tag.get(attr), base_url, candidate_urls)

    return candidate_urls


async def _url_exists(session: aiohttp.ClientSession, url: str) -> bool:
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


async def choose_preferred_media_url(
    session: aiohttp.ClientSession, candidate_urls: list[str]
) -> str | None:
    if not candidate_urls:
        return None

    for url in candidate_urls:
        if url.lower().endswith(".gif"):
            return url

    for url in candidate_urls:
        lower = url.lower()
        if lower.endswith(".mp4"):
            gif_candidate = url[:-4] + ".gif"
            if await _url_exists(session, gif_candidate):
                return gif_candidate

    for ext in (".mp4", ".webm"):
        for url in candidate_urls:
            if url.lower().endswith(ext):
                return url

    return candidate_urls[0]


async def resolve_ifunny_media_url(ifunny_link: str) -> str:
    if not is_ifunny_link(ifunny_link):
        raise ValueError("⚠️ Invalid link source. Only ifunny.co links are allowed.")

    async with aiohttp.ClientSession(headers=IFUNNY_HEADERS) as session:
        async with session.get(ifunny_link) as response:
            if response.status != 200:
                raise RuntimeError(f"Failed to fetch meme page: {response.status}")
            html = await response.text()

        candidate_urls = extract_ifunny_media_urls(html, ifunny_link)

        media_url = await choose_preferred_media_url(session, candidate_urls)

        if not media_url:
            raise ValueError("Could not find meme in the link.")

        return media_url


def _collect_meta(soup: BeautifulSoup) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        value = tag.get("content")
        if key and value:
            meta[key.lower()] = value
    return meta


def extract_instagram_media_from_meta(soup: BeautifulSoup) -> list[ResolvedMedia]:
    meta = _collect_meta(soup)

    for key in ("og:video:secure_url", "og:video:url", "og:video"):
        candidate = meta.get(key)
        if candidate:
            return [ResolvedMedia(url=candidate, is_video=True)]

    image = meta.get("og:image")
    if image:
        return [ResolvedMedia(url=image, is_video=False)]

    return []


def _extract_instagram_shortcode(instagram_link: str) -> tuple[str, str, dict[str, list[str]]]:
    parsed = urlparse(instagram_link)
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if len(path_segments) < 2:
        raise ValueError("Unrecognized Instagram URL format; expected /<type>/<shortcode>/")
    shortcode = path_segments[1]
    canonical_path = "/".join(path_segments[:2]) + "/"
    query_params = parse_qs(parsed.query)
    return shortcode, canonical_path, query_params


def _media_from_graph_node(node: dict) -> ResolvedMedia | None:
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


async def _resolve_instagram_via_graphql(
    session: aiohttp.ClientSession, instagram_link: str, lsd_token: str | None
) -> list[ResolvedMedia]:
    shortcode, canonical_path, query_params = _extract_instagram_shortcode(instagram_link)

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
        "X-IG-App-ID": INSTAGRAM_GRAPHQL_APP_ID,
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
        "doc_id": INSTAGRAM_GRAPHQL_DOC_ID,
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
            resolved = _media_from_graph_node(node)
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


async def resolve_instagram_media(instagram_link: str) -> list[ResolvedMedia]:
    if not is_instagram_link(instagram_link):
        raise ValueError("⚠️ Invalid link source. Only instagram.com links are allowed.")

    query_params = parse_qs(urlparse(instagram_link).query)

    async with aiohttp.ClientSession(headers=INSTAGRAM_HEADERS) as session:
        try:
            async with session.get(instagram_link) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to fetch Instagram page: {response.status}")
                html = await response.text()
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Failed to fetch Instagram page: {exc}") from exc

        soup = BeautifulSoup(html, "html.parser")
        media_items = extract_instagram_media_from_meta(soup)
        lsd_token = None

        if media_items and not (query_params.get("img_index") or query_params.get("img_index[]")):
            return media_items

        for pattern in LSD_PATTERNS:
            match = pattern.search(html)
            if match:
                lsd_token = match.group(1)
                break

        return await _resolve_instagram_via_graphql(session, instagram_link, lsd_token)


def extract_first_matching_url(
    content: str, predicate: Callable[[str], bool]
) -> str | None:
    for match in URL_REGEX.finditer(content):
        candidate = match.group(0).strip("<>")
        candidate = candidate.rstrip(").,")
        if predicate(candidate):
            return candidate
    return None


def filename_from_url(url: str, is_video: bool | None = None) -> str:
    path = urlsplit(url).path
    name = path.rsplit("/", 1)[-1] or "media"
    if not os.path.splitext(name)[1] and is_video is not None:
        name += ".mp4" if is_video else ".jpg"
    return name


def format_slop(url: str) -> str:
    return f"[slop]({url})"


async def deliver_media(
    message: discord.Message, media_url: str, headers: dict[str, str], is_video: bool | None = None
) -> None:
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(media_url) as media_response:
                if media_response.status != 200:
                    await message.channel.send("Failed to download media.")
                    return

                size_header = media_response.headers.get("Content-Length")
                if size_header and int(size_header) > MAX_DISCORD_FILE_SIZE:
                    await message.channel.send(format_slop(media_url))
                    return

                media_bytes = await media_response.read()

        if len(media_bytes) > MAX_DISCORD_FILE_SIZE:
            await message.channel.send(format_slop(media_url))
            return

        filename = filename_from_url(media_url, is_video)
        await message.channel.send(file=discord.File(io.BytesIO(media_bytes), filename=filename))
    except Exception as exc:
        await message.channel.send(f"Failed to deliver media: {exc}")


class MyClient(discord.Client):
    async def on_ready(self):
        print(f"{self.user} online")

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content.startswith("Tap to see the meme -"):
            ifunny_link = message.content.split("Tap to see the meme -", 1)[1].strip()
            await self._handle_ifunny(message, ifunny_link)
            return

        instagram_link = extract_first_matching_url(message.content, is_instagram_link)
        if instagram_link:
            await self._handle_instagram(message, instagram_link)

    async def _handle_ifunny(self, message: discord.Message, ifunny_link: str) -> None:
        if not is_ifunny_link(ifunny_link):
            await message.channel.send("⚠️ Invalid link source. Only ifunny.co links are allowed.")
            return

        try:
            media_url = await resolve_ifunny_media_url(ifunny_link)
        except Exception as exc:
            await message.channel.send(f"Error processing the link: {exc}")
            return

        await deliver_media(message, media_url, IFUNNY_HEADERS, is_video=None)

    async def _handle_instagram(self, message: discord.Message, instagram_link: str) -> None:
        try:
            media_items = await resolve_instagram_media(instagram_link)
        except Exception as exc:
            await message.channel.send(f"Error processing the Instagram link: {exc}")
            return

        if not media_items:
            await message.channel.send("Could not find media in the link.")
            return

        for item in media_items:
            await deliver_media(message, item.url, INSTAGRAM_HEADERS, is_video=item.is_video)


async def _run_cli(url: str) -> None:
    if is_ifunny_link(url):
        media_url = await resolve_ifunny_media_url(url)
        print(format_slop(media_url))
        return

    if is_instagram_link(url):
        items = await resolve_instagram_media(url)
        for item in items:
            print(format_slop(item.url))
        return

    raise SystemExit("Error: Unsupported URL domain.")


def main():
    parser = argparse.ArgumentParser(description="Ifunny/Instagram resolver bot/cli entry point")
    parser.add_argument("--url", help="Resolve a single supported link locally")
    args = parser.parse_args()

    if args.url:
        try:
            asyncio.run(_run_cli(args.url))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return

    token = os.getenv("TOKEN")
    if not token:
        print("TOKEN environment variable not set.", file=sys.stderr)
        raise SystemExit(1)

    intents = discord.Intents.default()
    intents.message_content = True

    client = MyClient(intents=intents)
    client.run(token)


if __name__ == "__main__":
    main()
