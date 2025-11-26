import os
import time
import asyncio
import discord
from discord.ext import commands, tasks
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
SESSION_TIMEOUT = 3600
target_news_channel_id = None # Stores the channel for auto-updates

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    # Start the background task if not already running
    if not auto_news_loop.is_running():
        auto_news_loop.start()

# --- HELPER: MEMORY ---
def get_chat_history(channel_id, user_id):
    key = (channel_id, user_id)
    current_time = time.time()
    if key in chat_sessions:
        session_data = chat_sessions[key]
        if current_time - session_data['last_active'] > SESSION_TIMEOUT:
            chat_sessions[key] = {'history': [{"role": "system", "content": SYSTEM_PROMPT}], 'last_active': current_time}
        else:
            session_data['last_active'] = current_time
    else:
        chat_sessions[key] = {'history': [{"role": "system", "content": SYSTEM_PROMPT}], 'last_active': current_time}
    return chat_sessions[key]['history']

# --- HELPER: RSS FETCHING ---
def fetch_feed(url):
    return feedparser.parse(url)

# --- LOGIC: GENERATE URGENT REPORT ---
async def generate_urgent_report_content():
    """
    Core logic for !urgente and the 2-hour loop.
    1. Gets Trending Topics.
    2. Gets GE (Sports) - Force Top 10.
    3. Gets G1 (General).
    4. Searches Trending Topics in Google News.
    5. Curates with Groq.
    """
    try:
        loop = asyncio.get_event_loop()
        
        # 1. Get Trends first (to know what to search)
        trends_url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=BR"
        trends_feed = await loop.run_in_executor(None, fetch_feed, trends_url)
        
        top_trends = []
        if trends_feed.entries:
            # Get top 3 trending topics
            top_trends = [entry.title for entry in trends_feed.entries[:3]]
        
        # 2. Prepare Feed URLs
        ge_url = "https://ge.globo.com/rss/ge/"
        g1_url = "https://g1.globo.com/rss/g1/"
        
        tasks_list = [
            loop.run_in_executor(None, fetch_feed, ge_url),
            loop.run_in_executor(None, fetch_feed, g1_url)
        ]
        
        # Add searches for trending topics
        for trend in top_trends:
            search_url = f"https://news.google.com/rss/search?q={quote(trend)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            tasks_list.append(loop.run_in_executor(None, fetch_feed, search_url))

        # 3. Fetch All
        results = await asyncio.gather(*tasks_list)
        
        feed_ge = results[0]
        feed_g1 = results[1]
        trend_feeds = results[2:]

        candidates = []

        # -- PROCESS GE (SPORTS) --
        # Requirement: Top 10 GE news always extracted
        if feed_ge.entries:
            for entry in feed_ge.entries[:10]:
                candidates.append(f"TIPO: ESPORTE (GE) | TÍTULO: {entry.title} | LINK: {entry.link}")

        # -- PROCESS TRENDS RESULTS --
        for i, feed in enumerate(trend_feeds):
            topic_name = top_trends[i]
            if feed.entries:
                for entry in feed.entries[:3]: # Top 3 per trend
                    candidates.append(f"TIPO: TRENDING ({topic_name}) | TÍTULO: {entry.title} | LINK: {entry.link}")

        # -- PROCESS G1 (GENERAL) --
        if feed_g1.entries:
            for entry in feed_g1.entries[:5]:
                candidates.append(f"TIPO: GERAL (G1) | TÍTULO: {entry.title} | LINK: {entry.link}")

        if not candidates:
            return "Paizão, tentei varrer a internet mas tá tudo fora do ar."

        # 4. Groq Curation
        news_data = "\n".join(candidates)
        
        curation_prompt = f"""
        Aja como o "Gozão".
        Eu coletei notícias do Globo Esporte (GE), G1 e Google Trends.
        
        LISTA DE DADOS:
        {news_data}

        TAREFA:
        Crie um relatório "URGENTE" com exatamente duas seções:
        
        SEÇÃO 1: ⚽ ESPORTES
        - Selecione as 5 notícias mais importantes marcadas como ESPORTE (GE).
        
        SEÇÃO 2: 🌍 GERAL & TRENDS
        - Selecione as 5 notícias mais importantes de GERAL (G1) ou TRENDING.
        - Dê prioridade para os assuntos do momento (Trending).

        REGRAS:
        - Use apenas Título e Link.
        - Sem resumos longos.
        - Títulos engraçadinhos estilo "Paizão" são permitidos.
        
        FORMATO FINAL:
        🚨 **PLANTÃO DO GOZÃO - URGENTE** 🚨

        ⚽ **ESPORTES**
        1. [Título] 
        🔗 [Link]
        ...

        🌍 **GERAL & TRENDS**
        1. [Título]
        🔗 [Link]
        ...
        """

        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": curation_prompt}],
            temperature=0.4,
            max_tokens=1000,
            stream=False
        )

        return completion.choices[0].message.content

    except Exception as e:
        print(f"Urgent Error: {e}")
        return f"Paizão, deu ruim no relatório urgente: {e}"

# --- BACKGROUND TASK (Every 2 Hours) ---
@tasks.loop(hours=2)
async def auto_news_loop():
    global target_news_channel_id
    if target_news_channel_id:
        channel = bot.get_channel(target_news_channel_id)
        if channel:
            try:
                # Send a typing indicator purely for visual effect if possible (needs context, skipped here)
                report = await generate_urgent_report_content()
                await channel.send(report)
            except Exception as e:
                print(f"Auto loop error: {e}")

# --- COMMAND: URGENTE (Manual Trigger + Set Channel) ---
@bot.command(name="urgente")
async def urgent_command(ctx):
    """
    Triggers the report immediately and sets this channel for auto-updates.
    """
    global target_news_channel_id
    target_news_channel_id = ctx.channel.id # Set current channel for future auto-updates
    
    await ctx.send("🚨 **Segura que o pai tá compilando o que tá bombando!** (Configurado para mandar aqui a cada 2h)")
    
    async with ctx.typing():
        report = await generate_urgent_report_content()
        await ctx.send(report)

# --- COMMAND: NEWS (UNCHANGED - As requested) ---
@bot.command(name="news")
async def get_news(ctx, *, topic="tecnologia"):
    async with ctx.typing():
        try:
            encoded_topic = quote(topic)
            google_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            g1_url = "https://g1.globo.com/rss/g1/"
            ge_url = "https://ge.globo.com/rss/ge/"
            
            loop = asyncio.get_event_loop()
            feed_google_future = loop.run_in_executor(None, fetch_feed, google_url)
            feed_g1_future = loop.run_in_executor(None, fetch_feed, g1_url)
            feed_ge_future = loop.run_in_executor(None, fetch_feed, ge_url)

            try:
                feed_google, feed_g1, feed_ge = await asyncio.wait_for(
                    asyncio.gather(feed_google_future, feed_g1_future, feed_ge_future),
                    timeout=15.0 
                )
            except asyncio.TimeoutError:
                await ctx.send("Paizão, a internet tá de rosca. Demorou demais e deu timeout.")
                return

            candidates = []
            topic_keywords = [w.lower() for w in topic.split() if len(w) > 2]

            def process_globo_feed(feed, source_label):
                if feed.entries:
                    for entry in feed.entries:
                        if any(k in entry.title.lower() for k in topic_keywords) or topic.lower() in entry.title.lower():
                            candidates.append(f"FONTE: {source_label} | TÍTULO: {entry.title} | LINK: {entry.link}")

            process_globo_feed(feed_ge, "GloboEsporte")
            process_globo_feed(feed_g1, "G1")

            if feed_google.entries:
                for entry in feed_google.entries[:10]:
                    candidates.append(f"FONTE: GoogleNews | TÍTULO: {entry.title} | LINK: {entry.link}")

            if not candidates:
                await ctx.send(f"Paizão, procurei no Google, G1 e GE mas não achei nada sobre '{topic}'.")
                return

            news_data = "\n".join(candidates)
            
            curation_prompt = f"""
            Aja como o "Gozão".
            Tópico pesquisado: "{topic}".
            LISTA DE NOTÍCIAS BRUTAS: {news_data}
            TAREFA:
            1. Selecione entre 3 a 5 notícias mais relevantes.
            2. PRIORIZE notícias do G1 e GloboEsporte.
            3. Tente diversificar as fontes se possível.
            4. Ignore notícias repetidas.
            5. NÃO ESCREVA RESUMO. Apenas o Título e o Link.
            FORMATO DA RESPOSTA:
            **📰 Notícias brabas sobre {topic}:**
            1. [Emoji] **[Título]**
            🔗 [Link Original]
            2. ...
            """

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": curation_prompt}],
                temperature=0.3,
                max_tokens=800,
                stream=False
            )
            await ctx.send(completion.choices[0].message.content)

        except Exception as e:
            print(f"News Error: {e}")
            await ctx.send("Paizão, deu um erro na hora de buscar as notícias.")

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

# --- COMMAND: MEME ---
@bot.command(name="meme")
async def send_meme(ctx):
    memes = [
        "https://cdn.discordapp.com/attachments/1302528042224324618/1428482038402519062/WhatsApp_Image_2025-10-16_at_17.33.47.jpeg?ex=69261391&is=6924c211&hm=66b83e1a15df04d0d1a23fe737b96aa5cbc70d7f3eca0c7aff5499dc2f783305&",
    ]
    await ctx.send(random.choice(memes))

# --- COMMAND: RESET ---
@bot.command(name="reset")
async def reset_memory(ctx):
    key = (ctx.channel.id, ctx.author.id)
    if key in chat_sessions:
        del chat_sessions[key]
        await ctx.send("🧠 Memória apagada! O Llama esqueceu tudo.")
    else:
        await ctx.send("🧠 Você não tinha nenhuma conversa ativa aqui.")

# --- MAIN EXECUTION ---
keep_alive()
bot.run(DISCORD_TOKEN)