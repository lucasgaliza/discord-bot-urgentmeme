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
from urllib.parse import quote
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
    
    try:
        published_time = datetime.fromtimestamp(mktime(entry.published_parsed))
        now = datetime.now()
        # 24 hours tolerance
        return (now - published_time) < timedelta(hours=24)
    except:
        return True # Fallback if date parsing fails

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
@bot.command(name="news") # Mantendo nome 'news' mas com lógica nova
async def get_news(ctx, *, topic="tecnologia"):
    """
    Fetches news from Google and G1, filters duplicates via Groq, and ensures freshness.
    """
    async with ctx.typing():
        try:
            # 1. Define Feed URLs
            # Encode topic to handle spaces (e.g. "santos e flamengo" -> "santos%20e%20flamengo")
            encoded_topic = quote(topic)
            
            # Google News (Search)
            google_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            
            # G1 (Main Feed & GE - trying to cover more ground)
            g1_url = "https://g1.globo.com/rss/g1/"
            
            # 2. Run fetching in a separate thread to prevent bot timeout
            loop = asyncio.get_event_loop()
            feed_google_future = loop.run_in_executor(None, fetch_feed, google_url)
            feed_g1_future = loop.run_in_executor(None, fetch_feed, g1_url)

            # Wait for both
            feed_google, feed_g1 = await asyncio.gather(feed_google_future, feed_g1_future)

            # 3. Collect and Pre-filter Candidates
            candidates = []
            
            # Prepare keywords for G1 filtering (split topic into words, ignore small words like 'e', 'do')
            topic_keywords = [w.lower() for w in topic.split() if len(w) > 2]

            # Process G1 Entries (PRIORITY)
            if feed_g1.entries:
                for entry in feed_g1.entries:
                    if is_recent(entry):
                        # Check if any keyword matches the title
                        if any(k in entry.title.lower() for k in topic_keywords) or topic.lower() in entry.title.lower():
                            candidates.append(f"FONTE: G1 | TÍTULO: {entry.title} | LINK: {entry.link}")

            # Process Google Entries
            if feed_google.entries:
                for entry in feed_google.entries[:10]: # Get top 10 to ensure variety
                    if is_recent(entry):
                        candidates.append(f"FONTE: GoogleNews | TÍTULO: {entry.title} | LINK: {entry.link}")

            if not candidates:
                await ctx.send(f"Paizão, procurei no Google e no G1 mas não achei nada recente (últimas 24h) sobre '{topic}'.")
                return

            # 4. Send to Groq for Curation and Formatting
            news_data = "\n".join(candidates)
            
            curation_prompt = f"""
            Aja como o "Gozão".
            Tópico pesquisado: "{topic}".
            
            LISTA DE NOTÍCIAS BRUTAS:
            {news_data}

            TAREFA:
            1. Selecione entre 3 a 5 notícias mais relevantes e RECENTES.
            2. **PRIORIZE notícias do G1**. Se houver notícias do G1 na lista, elas devem aparecer primeiro.
            3. Tente diversificar: Se possível, pegue pelo menos uma do G1 e uma do GoogleNews (se forem relevantes).
            4. Ignore notícias repetidas (mesmo assunto com títulos parecidos).
            5. Para cada notícia, escreva um resumo curto no seu estilo "Paizão".
            
            FORMATO DA RESPOSTA:
            **📰 Notícias brabas sobre {topic}:**

            1. [Emoji] **[Título Resumido]**
            [Resumo estilo Gozão]
            🔗 [Link Original]

            2. ...
            """

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": curation_prompt}],
                temperature=0.4, # Lower temperature for better fact selection
                max_tokens=1000,
                stream=False
            )

            final_response = completion.choices[0].message.content
            await ctx.send(final_response)

        except Exception as e:
            print(f"News Error: {e}")
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