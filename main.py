import os
import discord
from discord.ext import commands
import google.generativeai as genai
import feedparser
import random
from keep_alive import keep_alive

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

@bot.command(name="ask")
async def ask_gemini(ctx, *, prompt):
    async with ctx.typing():
        try:
            response = model.generate_content(prompt)
            text = response.text
            if len(text) > 2000:
                text = text[:1900] + "... (response truncated)"
            await ctx.send(text)
        except Exception as e:
            await ctx.send(f"Error: {e}")

@bot.command(name="news")
async def get_news(ctx, topic="technology"):
    async with ctx.typing():
        rss_url = f"https://news.google.com/rss/search?q={topic}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            await ctx.send(f"No news found for '{topic}'.")
            return
        entries = feed.entries[:3]
        message = f"**📰 Top News for {topic}:**\n"
        for entry in entries:
            message += f"- [{entry.title}]({entry.link})\n"
        
        await ctx.send(message)

@bot.command(name="meme")
async def send_meme(ctx):
    memes = [
        "https://cdn.discordapp.com/attachments/1302528042224324618/1428482038402519062/WhatsApp_Image_2025-10-16_at_17.33.47.jpeg?ex=69261391&is=6924c211&hm=66b83e1a15df04d0d1a23fe737b96aa5cbc70d7f3eca0c7aff5499dc2f783305&",
    ]
    await ctx.send(random.choice(memes))

keep_alive()
bot.run(DISCORD_TOKEN)