import argparse
import asyncio
import os
import sys
import discord
from client import MyClient

async def _run_cli(client: MyClient, url: str) -> None:
    for app in client.apps:
        if app.is_link(url):
            await app.resolve(url)
            return

    raise SystemExit("Error: Unsupported URL domain.")


def main():
    parser = argparse.ArgumentParser(description="Ifunny/Instagram resolver bot/cli entry point")
    parser.add_argument("--url", help="Resolve a single supported link locally")
    args = parser.parse_args()

    token = os.getenv("TOKEN")
    if not token:
        print("TOKEN environment variable not set.", file=sys.stderr)
        raise SystemExit(1)

    intents = discord.Intents.default()
    intents.message_content = True

    client = MyClient(intents=intents)
    client.run(token)

    if args.url:
        try:
            asyncio.run(_run_cli(client, args.url))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1)
        return

if __name__ == "__main__":
    main()