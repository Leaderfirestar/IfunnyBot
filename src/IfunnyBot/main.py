import argparse
import asyncio
import io
import os
import sys

import aiohttp
import discord
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urlparse, urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ifunny.co/",
    "Connection": "keep-alive",
}

MAX_DISCORD_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

load_dotenv()


def is_ifunny_link(url: str) -> bool:
    parsed_url = urlparse(url)
    return parsed_url.netloc.lower().endswith("ifunny.co")


def _add_candidate(url: str, base_url: str, collector: list) -> None:
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
    candidate_urls = []

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
                # Some CDNs reject HEAD, so fall back to a minimal GET probe
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

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(ifunny_link) as response:
            if response.status != 200:
                raise RuntimeError(f"Failed to fetch meme page: {response.status}")
            html = await response.text()

        candidate_urls = extract_ifunny_media_urls(html, ifunny_link)

        media_url = await choose_preferred_media_url(session, candidate_urls)

        if not media_url:
            raise ValueError("Could not find meme in the link.")

        return media_url


class MyClient(discord.Client):
    async def on_ready(self):
        print(f"{self.user} online")

    async def on_message(self, message):
        if message.author == self.user:
            return
        if not message.content.startswith("Tap to see the meme -"):
            return
        # get the Ifunny link from the message
        ifunny_link = message.content.split("Tap to see the meme -")[1].strip()

        if not is_ifunny_link(ifunny_link):
            await message.channel.send("⚠️ Invalid link source. Only ifunny.co links are allowed.")
            return

        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(ifunny_link) as response:
                    if response.status != 200:
                        await message.channel.send(f"Failed to fetch meme page: {response.status}")
                        return

                    html = await response.text()
                    candidate_urls = extract_ifunny_media_urls(html, ifunny_link)

                    media_url = await choose_preferred_media_url(session, candidate_urls)

                    if not media_url:
                        await message.channel.send("Could not find meme in the link.")
                        return

                    # Fetch the media itself
                    async with session.get(media_url) as media_response:
                        if media_response.status != 200:
                            await message.channel.send("Failed to download meme.")
                            return

                        size = int(media_response.headers.get("Content-Length", 0))
                        if size > MAX_DISCORD_FILE_SIZE:
                            await message.channel.send(media_url)
                            return

                        media_bytes = await media_response.read()
                        filename = media_url.split("/")[-1]

                        # Send the file to Discord
                        await message.channel.send(
                            file=discord.File(io.BytesIO(media_bytes), filename=filename)
                        )
        except Exception as e:
            await message.channel.send(f"Error processing the link: {str(e)}")


async def _run_cli(url: str) -> None:
    resolved = await resolve_ifunny_media_url(url)
    print(resolved)


def main():
    parser = argparse.ArgumentParser(description="Ifunny resolver bot/cli entry point")
    parser.add_argument("--url", help="Resolve a single iFunny link locally")
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
