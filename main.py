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
GROQ_MODEL = "llama-3.3-70b-versatile"

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

meme_counter = 0

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


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

async def send_random_meme(channel_target):
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
        return

    msg = random.choice(messages)

    if msg.content:
        response_text = f"\n>>> {msg.content}"
    else:
        response_text = f"\n{msg.attachments[0].url}"

    await channel_target.send(response_text)

async def generate_urgent_report_content(item_count=5):
    try:
        loop = asyncio.get_event_loop()
        
        trends_url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=BR"
        trends_feed = await loop.run_in_executor(None, fetch_feed, trends_url)
        
        trends_limit = 5 if item_count == 5 else 10
        top_trends = []
        if trends_feed.entries:
            top_trends = [entry.title for entry in trends_feed.entries[:trends_limit]]
        
        ge_url = "https://ge.globo.com/rss/ge/"
        g1_url = "https://g1.globo.com/rss/g1/"
        
        tasks_list = [
            loop.run_in_executor(None, fetch_feed, ge_url),
            loop.run_in_executor(None, fetch_feed, g1_url)
        ]
        
        search_limit = 3 if item_count == 5 else 5
        for trend in top_trends[:search_limit]: 
            search_url = f"https://news.google.com/rss/search?q={quote(trend)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            tasks_list.append(loop.run_in_executor(None, fetch_feed, search_url))

        results = await asyncio.gather(*tasks_list)
        
        feed_ge = results[0]
        feed_g1 = results[1]
        trend_feeds = results[2:]

        raw_candidates = []

        feed_limit = 15 if item_count == 5 else 25

        if feed_ge.entries:
            for entry in feed_ge.entries[:feed_limit]:
                raw_candidates.append({'source': 'ESPORTE (GE)', 'title': entry.title, 'link': entry.link})

        for i, feed in enumerate(trend_feeds):
            topic_name = top_trends[i]
            if feed.entries:
                for entry in feed.entries[:2]:
                    raw_candidates.append({'source': f'TRENDING ({topic_name})', 'title': entry.title, 'link': entry.link})

        if feed_g1.entries:
            for entry in feed_g1.entries[:feed_limit]:
                raw_candidates.append({'source': 'GERAL (G1)', 'title': entry.title, 'link': entry.link})

        if not raw_candidates:
            return "Mano, a internet tá de complô contra mim, não achei nada. Vou tomar uma."

        candidates = await shorten_candidates(raw_candidates, loop)
        news_data = "\n".join(candidates)
        
        curation_prompt = f"""
        
        DADOS BRUTOS:
        {news_data}

        TAREFA:
        Relatório "URGENTE":

        SEÇÃO 1: ⚽ ESPORTES
        - Selecione as {item_count} notícias mais relevantes de ESPORTE (GE).
        - Ignore notícias que são só anúncios de partidas ou placares.

        SEÇÃO 2: 🌍 GERAL & TRENDS
        - Selecione as {item_count} notícias mais importantes de GERAL (G1) ou TRENDING.

        REGRAS:
        - Títulos curtos.
        - NÃO FAÇA resumo. Só Título e Link.
        - Máximo de 1900 caracteres por bloco.

        FORMATO FINAL:
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

        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": curation_prompt}],
            temperature=0.6,
            max_tokens=700,
            stream=False
        )

        full_report = completion.choices[0].message.content

        try:
            esporte_part = full_report.split("🌍")[0].strip()
            geral_part = "🌍" + full_report.split("🌍")[1]
        except:
            esporte_part = full_report
            geral_part = "Erro ao separar sessões."

        return esporte_part, geral_part

    except Exception as e:
        print(f"Urgent Error: {e}")
        return f"A vida é injusta, deu erro até no meu relatório: {e}"

@tasks.loop(hours=1)
async def auto_news_loop():
    global target_news_channel_id
    if target_news_channel_id:
        channel = bot.get_channel(target_news_channel_id)
        if channel:
            try:
                esporte, geral = await generate_urgent_report_content(item_count=10)
                await channel.send(esporte)
                await channel.send(geral)
            except Exception as e:
                print(f"Auto loop error: {e}")

@tasks.loop(minutes=15)
async def auto_meme_loop():
    global meme_counter
    global target_news_channel_id

    meme_counter += 1

    if meme_counter == 4:
        meme_counter = 0
        return  

    if target_news_channel_id:
        channel = bot.get_channel(target_news_channel_id)
        if channel:
            try:
                await send_random_meme(channel)
            except Exception as e:
                print(f"Meme loop error: {e}")

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    if not auto_news_loop.is_running():
        auto_news_loop.start()
    if not auto_meme_loop.is_running():
        auto_meme_loop.start()

@bot.command(name="help")
async def help_command(ctx):
    help_text = """
    **MANUAL DO GOZÃO**

    🍺 `!gozão [texto]` - Fala comigo. Vou reclamar da vida e te responder (se eu quiser).
    🍺 `!news [tópico]` - Busco notícias sobre o que você pedir.
    🍺 `!urgente` - Mando um resumão do que tá rolando agora (5 de Esporte, 5 Gerais). Também configurado pra mandar sozinho aqui a cada 2h.
    🍺 `!meme [#canal]` - Trás uma mensagem aleatória do canal (padrão: #digo-menos).
    🍺 `!reset` - Apago minha memória. Bom pra quando eu começo a falar muita besteira.
    
    É isso, paizão.
    """
    await ctx.send(help_text)

@bot.command(name="meme")
async def meme_command(ctx, channel_target: discord.TextChannel = None):
    if channel_target is None:
        channel_target = discord.utils.get(ctx.guild.text_channels, name="digo-menos")
        if channel_target is None:
            await ctx.send("Mano, não achei o canal e tu não marcou nada.")
            return

    async with ctx.typing():
        try:
            await send_random_meme(channel_target)
        except Exception as e:
            await ctx.send(f"Mano, não tenho permissão == {e}")

@bot.command(name="urgente")
async def urgent_command(ctx):
    global target_news_channel_id
    target_news_channel_id = ctx.channel.id
        
    async with ctx.typing():
        esporte, geral = await generate_urgent_report_content(item_count=5)
        await ctx.send(esporte)
        await ctx.send(geral)

@bot.command(name="news")
async def get_news(ctx, *, topic="tecnologia"):
    async with ctx.typing():
        try:
            encoded_topic = quote(topic)
            google_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
            g1_url = "https://g1.globo.com/rss/g1/"
            ge_url = "https://ge.globo.com/rss/ge/"
            
            loop = asyncio.get_event_loop()
            feeds = await asyncio.gather(
                loop.run_in_executor(None, fetch_feed, google_url),
                loop.run_in_executor(None, fetch_feed, g1_url),
                loop.run_in_executor(None, fetch_feed, ge_url)
            )

            feed_google, feed_g1, feed_ge = feeds

            raw_candidates = []
            topic_keywords = [w.lower() for w in topic.split() if len(w) > 2]

            def process_feed(feed, source_name):
                if feed.entries:
                    for entry in feed.entries:
                        if any(k in entry.title.lower() for k in topic_keywords):
                            raw_candidates.append({'source': source_name, 'title': entry.title, 'link': entry.link})

            process_feed(feed_ge, "GloboEsporte")
            process_feed(feed_g1, "G1")

            if feed_google.entries:
                for entry in feed_google.entries[:10]:
                    raw_candidates.append({'source': "GoogleNews", 'title': entry.title, 'link': entry.link})

            if not raw_candidates:
                await ctx.send(f"Pô cara, procurei mas não achei nada de '{topic}'.")
                return

            candidates = await shorten_candidates(raw_candidates, loop)
            news_data = "\n".join(candidates)

            curation_prompt = f"""
            Persona: Gozão.
            Tópico: "{topic}".
            DADOS: {news_data}

            - Selecione 3 a 5 notícias.
            - Priorize G1/GE.
            - Sem resumo.
            - Só Título + Link.
            """

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": curation_prompt}],
                temperature=0.5,
                max_tokens=500,
                stream=False
            )

            await ctx.send(completion.choices[0].message.content)

        except Exception as e:
            await ctx.send("Deu erro, mano.")
            print(e)

@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt=None):
    if prompt is None:
        await ctx.send("Fala logo o que tu quer, tô com sede.")
        return

    async with ctx.typing():
        try:
            history = get_chat_history(ctx.channel.id, ctx.author.id)
            history.append({"role": "user", "content": prompt})

            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=history,
                temperature=1.0,
                max_tokens=250,
                top_p=1,
                stream=False
            )

            response_text = completion.choices[0].message.content
            history.append({"role": "assistant", "content": response_text})

            await ctx.send(response_text[:2000])

        except Exception as e:
            await ctx.send(f"Deu ruim no Groq: {e}")

@bot.command(name="reset")
async def reset_memory(ctx):
    key = (ctx.channel.id, ctx.author.id)
    if key in chat_sessions:
        del chat_sessions[key]
        await ctx.send("Esqueci tudo, paizão.")
    else:
        await ctx.send("Nem lembro de tu.")

keep_alive()
bot.run(DISCORD_TOKEN)