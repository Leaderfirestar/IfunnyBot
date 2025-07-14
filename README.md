# IfunnyBot 🤖

A lightweight, no-tracking Discord bot that returns memes from iFunny on demand.

[![Deploy Status](https://img.shields.io/github/actions/workflow/status/Leaderfirestar/IfunnyBot/deploy.yml?branch=master)](https://github.com/Leaderfirestar/IfunnyBot/actions)
[![MIT License](https://img.shields.io/github/license/Leaderfirestar/IfunnyBot)](LICENSE)

---

## 📝 Description

**IfunnyBot** is a Discord bot that fetches memes from iFunny and sends them back as images/videos in your server. It’s completely open source, lightweight, and respects your privacy.

No tracking. No data collection. Just memes.

---

## 📦 What It Does

**IfunnyBot** Responds to messages starting with `Tap to see the meme - ` by grabbing the link in the message, getting the image or video from that url, and sending the file to the channel the message was originally sent in

---

## 🔒 Required Permissions

To function properly, IfunnyBot needs the following permissions:

- `Read Messages`
- `Send Messages`

No other permissions are required or used.

---

## ⚙️ Setup Instructions

### Add the Bot to Your Server

> [Click here to invite the bot](https://discord.com/oauth2/authorize?client_id=1393976842536489060)

_Or clone the repo and self-host it (see below)._

### Running Locally

```bash
git clone https://github.com/Leaderfirestar/IfunnyBot.git
cd IfunnyBot

# Set up environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file with your Discord token
echo "TOKEN=your_discord_token" > .env

# Run the bot
python src/IfunnyBot/main.py
```

## 🛠️ How It Works

1. Uses discord.py to register an `on_message` listener
2. looks for messages starting with `Tap to see the meme - ` (The message you send to discord when sharing a link from iFunny looks like `Tap to see the meme -  https://ifunny.co/link-to-meme`)
3. Scrapes the meme from iFunny.
4. Converts it to an image in memory.
5. Sends it to the channel.

## 🤝 Contributing

I welcome contributions, ideas, or improvements!
See [CONTRIBUTING.md](CONTRIBUTING) for details.

If you find a bug or have a feature suggestion, feel free to open an issue.

## 🧾 License

This project is licensed under the [MIT License](LICENSE).

## 📄 Legal

- [Privacy Policy](privacy)
- [Terms of Service](TermsOfService)

> IfunnyBot does not collect, store, or transmit any personal data

## 💬 Questions?

Open an issue or start a discussion!
