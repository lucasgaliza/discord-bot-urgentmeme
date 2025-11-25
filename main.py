import os
import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import feedparser
import random
from keep_alive import keep_alive

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# --- GEMINI SETUP ---
genai.configure(api_key=GEMINI_KEY)

# 1. SYSTEM INSTRUCTION (The "Brain" Personality)
# This tells the bot HOW to behave globally. This fixes "poor" answers.
SYSTEM_PROMPT = """
Você se chama Gozão e é um assistente virtual brasileiro, gente boa e direto ao ponto.
Seu tom é informal, usando gírias leves quando apropriado (tipo "Paizão", "Chorão Skate Board", "ÉAHNNNNNN").
Você responde em Português do Brasil (PT-BR) nativo.
Seja conciso, mas prestativo.
"""

# Using gemini-2.5-flash with system instructions for better quality
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    system_instruction=SYSTEM_PROMPT
)

# --- MEMORY STORAGE ---
# Dictionary to store chat sessions: {channel_id: chat_session_object}
chat_sessions = {}

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

# --- HELPER: GET CHAT SESSION ---
def get_chat_session(channel_id):
    """
    Retrieves or creates a unique chat session for a specific channel.
    This allows the bot to 'remember' conversation context per channel.
    """
    if channel_id not in chat_sessions:
        # Start a new chat with empty history
        chat_sessions[channel_id] = model.start_chat(history=[])
    return chat_sessions[channel_id]

# --- COMMAND: ASK (With Memory) ---
@bot.command(name="ask")
async def ask_gemini(ctx, *, prompt):
    async with ctx.typing():
        try:
            # Get the session for this channel (Memory!)
            chat = get_chat_session(ctx.channel.id)
            
            # Send message to the chat session
            response = chat.send_message(prompt)
            
            # Safe text extraction
            try:
                text = response.text
            except ValueError:
                text = "⚠️ O Gemini não conseguiu gerar uma resposta de texto (Bloqueio ou erro interno)."

            if len(text) > 2000:
                text = text[:1900] + "... (response truncated)"
            await ctx.send(text)
        except Exception as e:
            # If memory breaks (rare), reset it
            if ctx.channel.id in chat_sessions:
                del chat_sessions[ctx.channel.id]
            await ctx.send(f"Erro (memória reiniciada): {e}")

# --- COMMAND: RESET MEMORY ---
@bot.command(name="reset")
async def reset_memory(ctx):
    """Clears the conversation history for the current channel."""
    if ctx.channel.id in chat_sessions:
        del chat_sessions[ctx.channel.id]
    await ctx.send("🧠 Memória apagada! O bot esqueceu o que conversamos neste canal.")

# --- COMMAND: GOZÃO (With Custom Config + Memory) ---
@bot.command(name="gozão")
async def gozao_command(ctx, *, prompt: str = None):
    if prompt is None:
        await ctx.send("Opa! Fala alguma coisa aí pra eu responder.")
        return

    async with ctx.typing():
        try:
            # 1. Custom Config for this command
            gen_config = {"max_output_tokens": 512, "temperature": 1.0}
            
            # 2. No Guardrails
            safety = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            # 3. Use Chat Session (Memory) OR Direct Generation?
            # Users usually expect specific commands to also have memory context.
            chat = get_chat_session(ctx.channel.id)
            
            # Send message with custom config
            response = chat.send_message(
                prompt,
                generation_config=gen_config,
                safety_settings=safety
            )
            
            # 4. Format and Send
            try:
                # Adding the prefix you requested
                answer = f"Paizão, é o seguinte: {response.text}"
            except ValueError:
                answer = "Paizão, é o seguinte: O Gemini travou e não soltou texto."

            if len(answer) > 2000:
                await ctx.send(answer[:1900] + "\n\n**(Cortado)**")
            else:
                await ctx.send(answer)

        except Exception as e:
            await ctx.send(f"Deu ruim: {e}")

# --- COMMAND: NEWS ---
@bot.command(name="news")
async def get_news(ctx, topic="technology"):
    async with ctx.typing():
        rss_url = f"https://news.google.com/rss/search?q={topic}&hl=pt-BR&gl=BR&ceid=BR:pt-419" # Updated to PT-BR news
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