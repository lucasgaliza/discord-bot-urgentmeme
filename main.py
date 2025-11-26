import os
import time
import asyncio
import discord
from discord.ext import commands
from groq import Groq
import feedparser
import random
from datetime import datetime, timedelta
from time import mktime
from keep_alive import keep_alive

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- GROQ SETUP ---
client = Groq(api_key=GROQ_API_KEY)
# Llama 3.3 is great for instruction following and Portuguese
GROQ_MODEL = "llama-3.3-70b-versatile" 

# --- SYSTEM INSTRUCTIONS ---
SYSTEM_PROMPT = """
Você se chama Gozão e é um assistente virtual brasileiro, gente boa e direto ao ponto.
Seu tom é informal, usando gírias leves quando apropriado (tipo "Paizão", "E o nosso Santos?", "ÉAAAAAAAAAAAAAAAAAAHN BUTECINHA").
Você responde em Português do Brasil (PT-BR) nativo e geralmente começa suas mensagens com "Paizão, é o seguinte:".
Seja conciso, mas prestativo.
"""

# --- MEMORY STORAGE ---
chat_sessions = {}
SESSION_TIMEOUT = 3600  # 1 Hour

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

# --- HELPER: MEMORY MANAGEMENT ---
def get_chat_history(channel_id, user_id):
    key = (channel_id, user_id)
    current_time = time.time()

    if key in chat_sessions:
        session_data = chat_sessions[key]
        if current_time - session_data['last_active'] > SESSION_TIMEOUT:
            # Reset expired session
            chat_sessions[key] = {
                'history': [{"role": "system", "content": SYSTEM_PROMPT}],
                'last_active': current_time
            }
        else:
            session_data['last_active'] = current_time
    else:
        # New Session
        chat_sessions[key] = {
            'history': [{"role": "system", "content": SYSTEM_PROMPT}],
            'last_active': current_time
        }
    
    return chat_sessions[key]['history']

# --- HELPER: RSS FETCHING ---
def fetch_feed(url):
    return feedparser.parse(url)

def is_recent(entry):
    """Checks if the news is from the last 24 hours."""
    if not hasattr(entry, 'published_parsed'):
        return True # If no date, assume valid to be safe, or False to be strict
    
    published_time = datetime.fromtimestamp(mktime(entry.published_parsed))
    now = datetime.now()
    # 24 hours tolerance
    return (now - published_time) < timedelta(hours=24)

# --- COMMAND: RESET ---
@bot.command(name="reset")
async def reset_memory(ctx):
    key = (ctx.channel.id, ctx.author.id)
    if key in chat_sessions:
        del chat_sessions[key]
        await ctx.send("🧠 Memória apagada! O Llama esqueceu tudo.")
    else:
        await ctx.send("🧠 Você não tinha nenhuma conversa ativa aqui.")

# --- COMMAND: GOZÃO (Chat) ---
@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Opa! Fala alguma coisa aí pra eu responder.")
        return

    async with ctx.typing():
        try:
            history = get_chat_history(ctx.channel.id, ctx.author.id)
            history.append({"role": "user", "content": prompt})

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=history,
                temperature=1.0,
                max_tokens=512,
                top_p=1,
                stream=False
            )
            
            response_text = completion.choices[0].message.content
            history.append({"role": "assistant", "content": response_text})

            if len(response_text) > 2000:
                await ctx.send(response_text[:1900] + "\n\n**(Cortado)**")
            else:
                await ctx.send(response_text)

        except Exception as e:
            await ctx.send(f"Deu ruim no Groq: {e}")

# --- COMMAND: NEWS (Enhanced) ---
@bot.command(name="news")
async def get_news(ctx, *, topic="tecnologia"):
    """
    Fetches news from Google and G1, filters duplicates via Groq, and ensures freshness.
    """
    async with ctx.typing():
        try:
            # 1. Define Feed URLs
            # Google News (Aggregator)
            google_url = f"https://news.google.com/rss/search?q={topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            # G1 (Main Feed - we will filter manually since they don't have a search RSS)
            g1_url = "https://g1.globo.com/rss/g1/"

            # 2. Run fetching in a separate thread to prevent bot timeout
            loop = asyncio.get_event_loop()
            feed_google_future = loop.run_in_executor(None, fetch_feed, google_url)
            feed_g1_future = loop.run_in_executor(None, fetch_feed, g1_url)

            # Wait for both
            feed_google, feed_g1 = await asyncio.gather(feed_google_future, feed_g1_future)

            # 3. Collect and Pre-filter Candidates
            candidates = []

            # Process Google Entries
            if feed_google.entries:
                for entry in feed_google.entries[:8]: # Limit to top 8 to save tokens
                    if is_recent(entry):
                        candidates.append(f"FONTE: GoogleNews | TÍTULO: {entry.title} | LINK: {entry.link}")

            # Process G1 Entries (Filter by topic similarity roughly or just add top ones)
            if feed_g1.entries:
                count = 0
                for entry in feed_g1.entries:
                    if count >= 5: break # Max 5 from G1
                    # Simple keyword check for relevance or just include headlines
                    if is_recent(entry):
                        # If topic is general, just add. If specific, check title.
                        if topic.lower() in entry.title.lower() or len(candidates) < 5:
                            candidates.append(f"FONTE: G1 | TÍTULO: {entry.title} | LINK: {entry.link}")
                            count += 1

            if not candidates:
                await ctx.send(f"Paizão, procurei no Google e no G1 mas não achei nada recente (últimas 24h) sobre '{topic}'.")
                return

            # 4. Send to Groq for Curation and Formatting
            # We give the raw list to the LLM and ask it to pick the best unique ones.
            news_data = "\n".join(candidates)
            
            curation_prompt = f"""
            Aja como o "Gozão" (seu sistema).
            Eu tenho uma lista de notícias brutas sobre o tema: "{topic}".
            
            LISTA DE NOTÍCIAS:
            {news_data}

            TAREFA:
            1. Selecione exatamente 3 notícias mais relevantes e DISTINTAS (não repita o mesmo assunto se tiver fontes diferentes).
            2. Se tiver menos de 3 notícias boas, mande as que tiver.
            3. Para cada notícia, escreva um resumo de uma linha no seu estilo "Paizão".
            4. Mantenha o LINK original de cada uma.
            
            FORMATO DA RESPOSTA:
            **📰 Notícias brabas sobre {topic}:**

            1. [Emoji] **[Título Resumido]**
            [Resumo estilo Gozão]
            🔗 [Link]

            2. ...
            """

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": curation_prompt}],
                temperature=0.5, # Lower temperature for factual news
                max_tokens=800,
                stream=False
            )

            final_response = completion.choices[0].message.content
            await ctx.send(final_response)

        except Exception as e:
            print(f"News Error: {e}") # Print to console for debug
            await ctx.send("Paizão, deu um erro na hora de buscar as notícias. Tenta de novo daqui a pouco.")

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