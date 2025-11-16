import discord
from apps.ifunny import IFunnyApp
from apps.instagram import InstagramApp
from apps.twitter import TwitterApp

class MyClient(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.apps = [IFunnyApp(), InstagramApp(), TwitterApp()]

    async def on_ready(self):
        print(f"{self.user} online")

    async def on_message(self, message):
        if message.author == self.user:
            return

        for app in self.apps:
            url = app.match(message.content)
            if url:
                await app.handle_message(message, url)
                break