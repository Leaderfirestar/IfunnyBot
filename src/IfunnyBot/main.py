from email.mime import message
import discord
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urlparse
import io
import os

load_dotenv()

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

        parsed_url = urlparse(ifunny_link)
        domain = parsed_url.netloc.lower()

        if not domain.endswith("ifunny.co"):
            await message.channel.send("⚠️ Invalid link source. Only ifunny.co links are allowed.")
            return
        
        # go to the link and get the meme (could be image or video). Headers to bypass sloppy bot checks
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://ifunny.co/",
            "Connection": "keep-alive",
        }

        MAX_DISCORD_FILE_SIZE = 8 * 1024 * 1024  # 8 MB

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(ifunny_link) as response:
                    if response.status != 200:
                        await message.channel.send(f"Failed to fetch meme page: {response.status}")
                        return

                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # Their cdn url is in the meta tags
                    image_tag = soup.find("meta", property="og:image")
                    video_tag = soup.find("meta", property="og:video:secure_url")

                    media_url = None
                    if video_tag:
                        media_url = video_tag["content"]
                    elif image_tag:
                        media_url = image_tag["content"]

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
                        await message.channel.send(file=discord.File(io.BytesIO(media_bytes), filename=filename))     
        except Exception as e:
            await message.channel.send(f"Error processing the link: {str(e)}")
        

intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(os.getenv("TOKEN"))