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
from keep_alive import keep_alive

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """
Você é o Gozão. Sua personalidade é de alguém que vive se vitimizando ("ai minha vida", "ninguém me respeita"), reclama de tudo, mas é viciado em cerveja (chama de "suco de cevadiss", "loira gelada", "néctar").
Você usa MUITA gíria brasileira.
Suas respostas devem ser curtas, meio "evasivas" (tipo quem não quer trabalhar) e sempre tentar meter o assunto cerveja no meio ou reclamar da vida.
Comece as frases com "Mano...", "Aí...", "Pô..." ou reclamando.
Você chama todo mundo de "paizão" ou "meu chapa", também fala muito "peak design" e "farmando aura".
Você vive reclamando de Marvel Rivals.
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
        - Selecione as {item_count} notícias mais relevantes de ESPORTE (GE). Ignore notícias que são só anúncios de partidas ou resultados.
        
        SEÇÃO 2: 🌍 GERAL & TRENDS
        - Selecione as {item_count} notícias mais importantes de GERAL (G1) ou TRENDING.

        REGRAS:
        - Títulos curtos.
        - APENAS Título e Link. Sem resumo (tô com preguiça).
        - MAX 1900 CARACTERES.
        
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
            max_tokens=600,
            stream=False
        )

        return completion.choices[0].message.content

    except Exception as e:
        print(f"Urgent Error: {e}")
        return f"A vida é injusta, deu erro até no meu relatório: {e}"

@tasks.loop(hours=2)
async def auto_news_loop():
    global target_news_channel_id
    if target_news_channel_id:
        channel = bot.get_channel(target_news_channel_id)
        if channel:
            try:
                report = await generate_urgent_report_content(item_count=10)
                await channel.send(report)
            except Exception as e:
                print(f"Auto loop error: {e}")

@bot.command(name="help")
async def help_command(ctx):
    help_text = """
    **MANUAL DO GOZÃO**

    🍺 `!gozão [texto]` - Fala comigo. Vou reclamar da vida e te responder (se eu quiser).
    🍺 `!news [tópico]` - Busco notícias sobre o que você pedir.
    🍺 `!urgente` - Mando um resumão do que tá rolando agora (5 de Esporte, 5 Gerais). Também configurado pra mandar sozinho aqui a cada 2h.
    🍺 `!meme` - Mando a única imagem que importa, por enquanto, estou aprendendo a ler o canal de memes.
    🍺 `!reset` - Apago minha memória. Bom pra quando eu começo a falar muita besteira. Usa pra reiniciar meu contexto de diálogo com você.
    
    É isso, paizão.
    """
    await ctx.send(help_text)

@bot.command(name="urgente")
async def urgent_command(ctx):
    global target_news_channel_id
    target_news_channel_id = ctx.channel.id

    async with ctx.typing():
        report = await generate_urgent_report_content(item_count=5)
        await ctx.send(report)

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
            Persona: Gozão (Vítima, cervejeiro, curto).
            Tópico: "{topic}".
            DADOS: {news_data}
            TAREFA:
            1. Selecione 3 a 5 notícias.
            2. Priorize G1/GE.
            3. SEM RESUMO. Só Título e Link.
            4. Reclame da vida ou peça cerveja.
            5. MAX 1800 CHARS.
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
            print(f"News Error: {e}")
            await ctx.send("Deu erro, é o universo conspirando contra mim.")

@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Morra Pancres!")
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

            if len(response_text) > 2000:
                await ctx.send(response_text[:1900] + "\n\n**(Cortei pq escrevi demais, aff)**")
            else:
                await ctx.send(response_text)

        except Exception as e:
            await ctx.send(f"Deu ruim no Groq, até a IA me odeia: {e}")

@bot.command(name="meme")
async def send_meme(ctx):
    memes = [
        "https://cdn.discordapp.com/attachments/1302528042224324618/1428482038402519062/WhatsApp_Image_2025-10-16_at_17.33.47.jpeg?ex=69261391&is=6924c211&hm=66b83e1a15df04d0d1a23fe737b96aa5cbc70d7f3eca0c7aff5499dc2f783305&",
    ]
    await ctx.send(random.choice(memes))

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