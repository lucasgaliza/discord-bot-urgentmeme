import os
import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import feedparser
import random
from keep_alive import keep_alive

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

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

@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Opa! Você precisa escrever algo depois do comando. Ex: `!gozão explique o que são buracos negros`")
        return

    async with ctx.typing():
        try:
            generation_config = {
                "max_output_tokens": 512,
                "temperature": 0.9,
            }

            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = model.generate_content(
                prompt,
                generation_config=generation_config,
                safety_settings=safety_settings
            )

            if response.text:
                answer = f"Paizão, é o seguinte: {response.text}"
            else:
                answer = "Paizão, é o seguinte: Você falou tanta bosta que nem minhas entradas captaram."

            # 5. Send (handling Discord limit)
            if len(answer) > 2000:
                await ctx.send(answer[:1900] + "\n\n**(Continua... resposta cortada pelo limite do Discord)**")
            else:
                await ctx.send(answer)

        except Exception as e:
            await ctx.send(f"Deu ruim no Gemini: {e}")

# --- MAIN EXECUTION ---
keep_alive()
bot.run(DISCORD_TOKEN)