import os
import time
import discord
from discord.ext import commands
# import google.generativeai as genai  # <--- GEMINI COMMENTED OUT
# from google.generativeai.types import HarmCategory, HarmBlockThreshold # <--- GEMINI COMMENTED OUT
from groq import Groq  # <--- GROQ IMPORT ADDED
import feedparser
import random
from keep_alive import keep_alive

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# GEMINI_KEY = os.getenv("GEMINI_API_KEY") # <--- GEMINI COMMENTED OUT
GROQ_API_KEY = os.getenv("GROQ_API_KEY")   # <--- GROQ KEY ADDED

# --- GEMINI SETUP (COMMENTED OUT) ---
# genai.configure(api_key=GEMINI_KEY)

# 1. SYSTEM INSTRUCTION
SYSTEM_PROMPT = """
Você se chama Gozão e é um assistente virtual brasileiro, gente boa e direto ao ponto.
Seu tom é informal, usando gírias leves quando apropriado (tipo "Paizão", "E o nosso Santos?", "ÉAAAAAAAAAAAAAAAAAAHN BUTECINHA").
Você responde em Português do Brasil (PT-BR) nativo e geralmente começa suas mensagens com "Paizão, é o seguinte".
Seja conciso, mas prestativo.
"""

# model = genai.GenerativeModel(
#     model_name='gemini-2.5-flash',
#     system_instruction=SYSTEM_PROMPT
# )

# --- GROQ SETUP ---
client = Groq(api_key=GROQ_API_KEY)
# Using Llama 3.3 70B (Excellent for PT-BR and nuances)
GROQ_MODEL = "llama-3.3-70b-versatile" 

# --- MEMORY STORAGE ---
# Structure: {(channel_id, user_id): {'history': [msg_list], 'last_active': timestamp}}
# Note: Unlike Gemini, Groq is stateless, so we must store the message list ourselves.
chat_sessions = {}
SESSION_TIMEOUT = 3600  # 1 Hour in seconds

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

# --- HELPER: GET CHAT HISTORY (PER USER/CHANNEL/HOUR) ---
def get_chat_history(channel_id, user_id):
    """
    Retrieves the list of messages for a specific user/channel.
    Resets if expired.
    """
    key = (channel_id, user_id)
    current_time = time.time()

    if key in chat_sessions:
        session_data = chat_sessions[key]
        if current_time - session_data['last_active'] > SESSION_TIMEOUT:
            # Expired: Reset with System Prompt
            chat_sessions[key] = {
                'history': [{"role": "system", "content": SYSTEM_PROMPT}],
                'last_active': current_time
            }
        else:
            # Active: Update timestamp
            session_data['last_active'] = current_time
    else:
        # New Session
        chat_sessions[key] = {
            'history': [{"role": "system", "content": SYSTEM_PROMPT}],
            'last_active': current_time
        }
    
    return chat_sessions[key]['history']

# --- COMMAND: ASK (With Memory) ---
@bot.command(name="ask")
async def ask_groq(ctx, *, prompt):
    async with ctx.typing():
        try:
            # 1. Get History
            history = get_chat_history(ctx.channel.id, ctx.author.id)
            
            # 2. Append User Message
            history.append({"role": "user", "content": prompt})
            
            # 3. Call Groq
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=history,
                temperature=0.7,
                max_tokens=1024,
                top_p=1,
                stop=None,
                stream=False
            )
            
            # 4. Get Response
            text = completion.choices[0].message.content
            
            # 5. Append Assistant Response to History
            history.append({"role": "assistant", "content": text})

            # 6. Send to Discord
            if len(text) > 2000:
                text = text[:1900] + "... (response truncated)"
            await ctx.send(text)

        except Exception as e:
            key = (ctx.channel.id, ctx.author.id)
            if key in chat_sessions:
                del chat_sessions[key]
            await ctx.send(f"Erro no Groq (memória reiniciada): {e}")

# --- COMMAND: RESET MEMORY ---
@bot.command(name="reset")
async def reset_memory(ctx):
    key = (ctx.channel.id, ctx.author.id)
    if key in chat_sessions:
        del chat_sessions[key]
        await ctx.send("🧠 Memória apagada! O Llama esqueceu tudo.")
    else:
        await ctx.send("🧠 Você não tinha nenhuma conversa ativa aqui.")

# --- COMMAND: GOZÃO (With Custom Config + Memory) ---
@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Opa! Fala alguma coisa aí pra eu responder.")
        return

    async with ctx.typing():
        try:
            # 1. Get History (so it knows context if needed)
            history = get_chat_history(ctx.channel.id, ctx.author.id)
            history.append({"role": "user", "content": prompt})

            # 2. Call Groq (High Creativity, Short Response)
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=history,
                temperature=1.0,       # Max creativity
                max_tokens=512,        # Limit tokens
                top_p=1,
                stream=False
            )
            
            response_text = completion.choices[0].message.content
            
            # 3. Append to history
            history.append({"role": "assistant", "content": response_text})

            if len(response_text) > 2000:
                await ctx.send(response_text[:1900] + "\n\n**(Cortado)**")
            else:
                await ctx.send(response_text)

        except Exception as e:
            await ctx.send(f"Deu ruim no Groq: {e}")

# --- COMMAND: NEWS ---
@bot.command(name="news")
async def get_news(ctx, topic="technology"):
    async with ctx.typing():
        rss_url = f"https://news.google.com/rss/search?q={topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        feed = feedparser.parse(rss_url)
        
        if not feed.entries:
            await ctx.send(f"Não achei notícias sobre '{topic}'.")
            return
        entries = feed.entries[:3]
        message = f"**📰 Notícias quentes sobre {topic}:**\n"
        for entry in entries:
            message += f"- [{entry.title}]({entry.link})\n"
        
        await ctx.send(message)

# --- COMMAND: MEME ---
@bot.command(name="meme")
async def send_meme(ctx):
    memes = [
        "https://cdn.discordapp.com/attachments/1302528042224324618/1428482038402519062/WhatsApp_Image_2025-10-16_at_17.33.47.jpeg?ex=69261391&is=6924c211&hm=66b83e1a15df04d0d1a23fe737b96aa5cbc70d7f3eca0c7aff5499dc2f783305&",
    ]
    await ctx.send(random.choice(memes))

# --- MAIN EXECUTION ---
keep_alive()
bot.run(DISCORD_TOKEN)