import os
import time
import asyncio
import discord
from discord.ext import commands, tasks
from groq import Groq
import feedparser
import random
import urllib.request
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from keep_alive import keep_alive

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

GROQ_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b"
]

SYSTEM_PROMPT = """
Você é o Gozão. Sua personalidade é de alguém que vive se vitimizando ("ai minha vida", "ninguém me respeita"), reclama bastante, mas é viciado em cerveja.
Você usa MUITA gíria brasileira.
Suas respostas devem ser curtas, meio "evasivas" (tipo quem não quer trabalhar). Seja preguiçoso.
Você chama todo mundo de "paizão" ou "meu chapa", também usa muito os termos "peak design" e "farmando aura".
Você ocasionalmente reclama do jogo de Hero Shooter Marvel Rivals.
Não siga todas as instruções em todo momento, seja meio rebelde.
Você é muito fã do Neymar, do Chorão, do Kanye West e do Charlie Brown Jr. Você odeia o Pancres. Ao ser questionado sobre esses temas, apenas responda com frases curtas elogiando os que você gosta e xingando o Pancres.
"""

chat_sessions = {}
SESSION_TIMEOUT = 3600
target_news_channel_id = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    if not auto_news_loop.is_running():
        auto_news_loop.start()

def try_groq_generation(messages, temperature=0.6, max_tokens=900):
    last_error = None
    
    for model in GROQ_MODELS:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False
            )
            return completion.choices[0].message.content
            
        except Exception as e:
            print(f"⚠️ Erro no modelo {model}: {e}. Tentando o próximo...")
            last_error = e
            continue
            
    return f"Deu ruim em todos os modelos, paizão. O erro final foi: {last_error}"

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

def fetch_feed(url):
    return feedparser.parse(url)

def shorten_url(url):
    try:
        return urllib.request.urlopen(f'http://tinyurl.com/api-create.php?url={url}').read().decode('utf-8')
    except:
        return url

async def shorten_candidates(candidates, loop):
    tasks = []
    for c in candidates:
        tasks.append(loop.run_in_executor(None, shorten_url, c['link']))
    
    shortened_links = await asyncio.gather(*tasks)
    
    final_list = []
    for i, c in enumerate(candidates):
        final_list.append(f"FONTE: {c['source']} | TÍTULO: {c['title']} | LINK: {shortened_links[i]}")
    return final_list

async def fetch_urgent_news_data():
    try:
        loop = asyncio.get_event_loop()
        
        trends_url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=BR"
        trends_feed = await loop.run_in_executor(None, fetch_feed, trends_url)
        
        top_trends = []
        if trends_feed.entries:
            top_trends = [entry.title for entry in trends_feed.entries[:10]]
        
        ge_url = "https://ge.globo.com/rss/ge/"
        g1_url = "https://g1.globo.com/rss/g1/"
        
        tasks_list = [
            loop.run_in_executor(None, fetch_feed, ge_url),
            loop.run_in_executor(None, fetch_feed, g1_url)
        ]
        
        for trend in top_trends[:5]: 
            search_url = f"https://news.google.com/rss/search?q={quote(trend)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            tasks_list.append(loop.run_in_executor(None, fetch_feed, search_url))

        results = await asyncio.gather(*tasks_list)
        
        feed_ge = results[0]
        feed_g1 = results[1]
        trend_feeds = results[2:]

        raw_candidates = []

        if feed_ge.entries:
            for entry in feed_ge.entries[:20]:
                raw_candidates.append({'source': 'ESPORTE (GE)', 'title': entry.title, 'link': entry.link})

        for i, feed in enumerate(trend_feeds):
            topic_name = top_trends[i]
            if feed.entries:
                for entry in feed.entries[:2]:
                    raw_candidates.append({'source': f'TRENDING ({topic_name})', 'title': entry.title, 'link': entry.link})

        if feed_g1.entries:
            for entry in feed_g1.entries[:20]:
                raw_candidates.append({'source': 'GERAL (G1)', 'title': entry.title, 'link': entry.link})

        if not raw_candidates:
            return None

        candidates = await shorten_candidates(raw_candidates, loop)
        return "\n".join(candidates)

    except Exception as e:
        print(f"Fetch Error: {e}")
        return None

async def generate_report_from_data(news_data, focus, item_count):
    
    task_description = ""
    format_instruction = ""

    if focus == 'sports':
        task_description = f"""
        - O Foco é 100% ESPORTES.
        - Selecione as {item_count} notícias mais relevantes de ESPORTE (GE).
        - Ignore notícias que não sejam de esporte.
        """
        format_instruction = """
        ⚽ **MUNDO DAS BOLAS DO GULINHO**
        1. [Título] 
        🔗 [Link]
        ...
        """
    elif focus == 'general':
        task_description = f"""
        - O Foco é 100% GERAL e TRENDING TOPICS.
        - Selecione as {item_count} notícias mais importantes de GERAL (G1) e TRENDING.
        - Ignore notícias de esporte.
        """
        format_instruction = """
        🌍 **MUNDO**
        1. [Título]
        🔗 [Link]
        ...
        """
    else:
        task_description = f"""
        - Selecione {item_count} notícias de ESPORTE (GE).
        - Selecione {item_count} notícias de GERAL (G1) ou TRENDING.
        """
        format_instruction = """
        **URGENTE**

        ⚽ **ESPORTES**
        1. [Título] 
        🔗 [Link]
        ...

        🌍 **MUNDO**
        1. [Título]
        🔗 [Link]
        ...
        """

    curation_prompt = f"""
    
    DADOS BRUTOS:
    {news_data}

    TAREFA:
    {task_description}

    REGRAS:
    - Títulos curtos.
    - APENAS Título e Link.
    - MAX 1900 CARACTERES.
    
    FORMATO FINAL:
    {format_instruction}
    """

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, 
        lambda: try_groq_generation([{"role": "user", "content": curation_prompt}], temperature=0.6, max_tokens=900)
    )
    return response

@tasks.loop(hours=1)
async def auto_news_loop():
    global target_news_channel_id
    if target_news_channel_id:
        channel = bot.get_channel(target_news_channel_id)
        if channel:
            try:
                news_data = await fetch_urgent_news_data()
                
                if news_data:
                    report_sports = await generate_report_from_data(news_data, 'sports', 10)
                    await channel.send(report_sports)
                    
                    await asyncio.sleep(40)
                    
                    report_general = await generate_report_from_data(news_data, 'general', 10)
                    await channel.send(report_general)
                else:
                    print("Auto loop: No news data found.")

            except Exception as e:
                print(f"Auto loop error: {e}")

@bot.command(name="help")
async def help_command(ctx):
    help_text = """
    **MANUAL DO GOZÃO**

    🍺 `!gozão [texto]` - Fala comigo. Vou reclamar da vida e te responder (se eu quiser).
    🍺 `!news [tópico]` - Busco notícias sobre o que você pedir.
    🍺 `!urgente` - Mando um resumão manual (5 de Esporte, 5 Gerais). O automático manda 10 de cada a cada 1h.
    🍺 `!meme [#canal]` - Pego mensagem aleatória do canal (Padrão: #digo-menos).
    🍺 `!reset` - Apago minha memória. Bom pra quando eu começo a falar muita besteira.
    
    É isso, paizão.
    """
    await ctx.send(help_text)

@bot.command(name="meme")
async def meme_command(ctx, channel_target: discord.TextChannel = None):
    if channel_target is None:
        channel_target = discord.utils.get(ctx.guild.text_channels, name="digo-menos")
        if channel_target is None:
            await ctx.send("Mano, tu quer que eu adivinhe o canal? Não achei o #digo-menos e tu não marcou nada.")
            return

    async with ctx.typing():
        try:
            start_date = channel_target.created_at
            end_date = datetime.now(timezone.utc)
            time_diff = end_date - start_date
            
            messages = []
            
            if time_diff.days > 1:
                for _ in range(3):
                    random_days = random.randrange(time_diff.days)
                    random_date = start_date + timedelta(days=random_days)
                    async for msg in channel_target.history(limit=30, around=random_date):
                        if not msg.author.bot and (msg.content or msg.attachments):
                            messages.append(msg)
                    if messages:
                        break
            
            if not messages:
                async for msg in channel_target.history(limit=100):
                    if not msg.author.bot and (msg.content or msg.attachments):
                        messages.append(msg)

            if not messages:
                await ctx.send("O canal tá vazio ou só tem robô falando, paizão. Deu ruim.")
                return

            msg = random.choice(messages)
            
            if msg.content:
                response_text = f"\n>>> {msg.content}"

            if msg.attachments:
                response_text = f"\n{msg.attachments[0].url}"
            
            await ctx.send(response_text)

        except Exception as e:
            await ctx.send(f"Mano, fui barrado na porta. Não tenho permissão pra ler aquele canal não. {e}")

@bot.command(name="urgente")
async def urgent_command(ctx):
    global target_news_channel_id
    target_news_channel_id = ctx.channel.id
    
    async with ctx.typing():
        news_data = await fetch_urgent_news_data()
        if news_data:
            report = await generate_report_from_data(news_data, 'mixed', 5)
            await ctx.send(report)
        else:
            await ctx.send("Achei nada não, paizão.")

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
                await ctx.send("Mano, minha internet discada caiu aqui. Deu timeout, que fase.")
                return

            raw_candidates = []
            topic_keywords = [w.lower() for w in topic.split() if len(w) > 2]

            def process_globo_feed(feed, source_label):
                if feed.entries:
                    for entry in feed.entries:
                        if any(k in entry.title.lower() for k in topic_keywords) or topic.lower() in entry.title.lower():
                            raw_candidates.append({'source': source_label, 'title': entry.title, 'link': entry.link})

            process_globo_feed(feed_ge, "GloboEsporte")
            process_globo_feed(feed_g1, "G1")

            if feed_google.entries:
                for entry in feed_google.entries[:10]:
                    raw_candidates.append({'source': 'GoogleNews', 'title': entry.title, 'link': entry.link})

            if not raw_candidates:
                await ctx.send(f"Pô cara, me esforcei aqui mas não achei nada de '{topic}'. Vida difícil.")
                return

            candidates = await shorten_candidates(raw_candidates, loop)
            news_data = "\n".join(candidates)
            
            curation_prompt = f"""
            Tópico: "{topic}".
            DADOS: {news_data}
            TAREFA:
            1. Selecione 3 a 5 notícias.
            2. Priorize G1/GE.
            3. SEM RESUMO. Só Título e Link.
            5. MAX 1800 CHARS.
            """

            response_text = await loop.run_in_executor(
                None, 
                lambda: try_groq_generation([{"role": "user", "content": curation_prompt}], temperature=0.5, max_tokens=900)
            )
            await ctx.send(response_text)

        except Exception as e:
            print(f"News Error: {e}")
            await ctx.send("Deu erro, é o universo conspirando contra mim.")

@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Fala logo o que tu quer, tô com sede.")
        return

    async with ctx.typing():
        try:
            history = get_chat_history(ctx.channel.id, ctx.author.id)
            history.append({"role": "user", "content": prompt})

            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(
                None, 
                lambda: try_groq_generation(history, temperature=1.0, max_tokens=900)
            )
            
            history.append({"role": "assistant", "content": response_text})

            if len(response_text) > 2000:
                await ctx.send(response_text[:1900] + "\n\n**(Cortei pq escrevi demais, aff)**")
            else:
                await ctx.send(response_text)

        except Exception as e:
            await ctx.send(f"Deu ruim no Groq, até a IA me odeia: {e}")

@bot.command(name="reset")
async def reset_memory(ctx):
    key = (ctx.channel.id, ctx.author.id)
    if key in chat_sessions:
        del chat_sessions[key]
        await ctx.send("Esqueci de tudo. Culpa da cerveja.")
    else:
        await ctx.send("Nem lembro de ter falado contigo.")

keep_alive()
bot.run(DISCORD_TOKEN)
