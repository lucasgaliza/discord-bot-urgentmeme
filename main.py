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
    Fetches news from Google, G1 and GE (Sports), filters via Groq.
    """
    async with ctx.typing():
        try:
            # 1. Define Feed URLs
            encoded_topic = quote(topic)
            
            # Google News (Search)
            google_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            
            # G1 (Main Feed)
            g1_url = "https://g1.globo.com/rss/g1/"

            # GE (Globo Esporte) - Added for sports priority
            ge_url = "https://ge.globo.com/rss/ge/"
            
            # 2. Run fetching in separate threads with TIMEOUT
            loop = asyncio.get_event_loop()
            feed_google_future = loop.run_in_executor(None, fetch_feed, google_url)
            feed_g1_future = loop.run_in_executor(None, fetch_feed, g1_url)
            feed_ge_future = loop.run_in_executor(None, fetch_feed, ge_url)

            try:
                # Wait for all feeds with a 15 second timeout
                feed_google, feed_g1, feed_ge = await asyncio.wait_for(
                    asyncio.gather(feed_google_future, feed_g1_future, feed_ge_future),
                    timeout=15.0 
                )
            except asyncio.TimeoutError:
                await ctx.send("Paizão, a internet tá de rosca. Demorou demais pra buscar as notícias e deu timeout.")
                return

            # 3. Collect Candidates (No date filter anymore)
            candidates = []
            
            # Prepare keywords for filtering G1/GE
            topic_keywords = [w.lower() for w in topic.split() if len(w) > 2]

            # Helper to process Globo/GE feeds
            def process_globo_feed(feed, source_label):
                if feed.entries:
                    for entry in feed.entries:
                        # Check if title matches topic keywords
                        if any(k in entry.title.lower() for k in topic_keywords) or topic.lower() in entry.title.lower():
                            candidates.append(f"FONTE: {source_label} | TÍTULO: {entry.title} | LINK: {entry.link}")

            # Process GE (Sports Priority)
            process_globo_feed(feed_ge, "GloboEsporte")

            # Process G1
            process_globo_feed(feed_g1, "G1")

            # Process Google Entries
            if feed_google.entries:
                for entry in feed_google.entries[:10]: # Get top 10 from Google
                    candidates.append(f"FONTE: GoogleNews | TÍTULO: {entry.title} | LINK: {entry.link}")

            if not candidates:
                await ctx.send(f"Paizão, procurei no Google, G1 e GE mas não achei nada sobre '{topic}'.")
                return

            # 4. Send to Groq for Curation
            news_data = "\n".join(candidates)
            
            curation_prompt = f"""
            Aja como o "Gozão".
            Tópico pesquisado: "{topic}".
            
            LISTA DE NOTÍCIAS BRUTAS:
            {news_data}

            TAREFA:
            1. Selecione entre 3 a 5 notícias mais relevantes.
            2. **PRIORIZE notícias do G1 e GloboEsporte**.
            3. Tente diversificar as fontes se possível.
            4. Ignore notícias repetidas.
            5. **NÃO ESCREVA RESUMO**. Apenas o Título e o Link.
            
            FORMATO DA RESPOSTA:
            **📰 Notícias brabas sobre {topic}:**

            1. [Emoji] **[Título]**
            🔗 [Link Original]

            2. ...
            """

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": curation_prompt}],
                temperature=0.3, # Low temp for precision
                max_tokens=800,
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