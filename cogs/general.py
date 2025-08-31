
import discord
from discord import app_commands
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check if the bot is responsive.")
    async def ping(self, interaction: discord.Interaction):
        """Simple ping command to test bot responsiveness."""
        try:
            # Respond immediately to avoid 3-second timeout
            latency = round(self.bot.latency * 1000)
            await interaction.response.send_message(f"🏓 Pong! Latency: {latency}ms")
        except discord.NotFound:
            # Interaction expired - log but don't try to respond
            print(f"Ping command timed out for user {interaction.user}")
        except Exception as e:
            print(f"Error in ping command: {e}")
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message("❌ Ping failed", ephemeral=True)
                except:
                    pass

async def setup(bot):
    await bot.add_cog(General(bot))