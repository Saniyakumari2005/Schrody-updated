import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import signal
import sys
import os
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# Configure logging for Railway (console output)
logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
                logging.StreamHandler(sys.stdout)  # Only console for Railway(might delete later)
        ]
)
logger = logging.getLogger(__name__)

# Bot intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

# Initialize bot with a slash command
class Schrody(commands.Bot):
        def __init__(self):
                super().__init__(command_prefix="!", intents=intents)
                self.cogs_loaded = False  # Track if cogs are already loaded

        async def setup_hook(self):
                """Sync commands when bot starts - only run once."""
                if self.cogs_loaded:
                        logger.info("Cogs already loaded, skipping setup_hook")
                        return

                logger.info("Loading cogs for the first time...")

                # List of cogs to load
                cogs_to_load = [
                        "cogs.tutor",
                        "cogs.feedback",
                        "cogs.database",
                        "cogs.general",
                        "cogs.reminder"
                ]

                for cog_name in cogs_to_load:
                        try:
                                await self.load_extension(cog_name)
                                logger.info(f"✅ Loaded {cog_name}")
                        except commands.ExtensionAlreadyLoaded:
                                logger.warning(f"⚠️ {cog_name} already loaded, skipping")
                        except Exception as e:
                                logger.error(f"❌ Failed to load {cog_name}: {e}")

                try:
                        await self.tree.sync()
                        logger.info(f"✅ Synced {len(self.tree.get_commands())} slash commands.")
                except Exception as e:
                        logger.error(f"❌ Failed to sync commands: {e}")


                self.cogs_loaded = True  # Mark cogs as loaded

        async def on_ready(self):
                """Called when bot is ready - can be called multiple times on reconnect."""
                logger.info(f"✅ Bot ready as {self.user}")
                logger.info(f'Bot is in {len(self.guilds)} guilds')

                # Set bot status (optional)
                await self.change_presence(
                        activity=discord.Activity(type=discord.ActivityType.watching, name="for commands")
                )

        async def on_message(self, message):
                """Prevent bot from processing commands in tutoring threads."""

                # Ignore bot messages
                if message.author == self.user:
                    return

                # Skip processing commands in Schrödy threads to avoid conflicts with tutor cog
                if (isinstance(message.channel, discord.Thread) and
                    message.channel.name.startswith("Schrödy-")):
                    return

                # Only process text commands (not slash commands)
                # Slash commands are handled automatically by discord.py
                await self.process_commands(message)

bot = Schrody()

# Global error handler
@bot.event
async def on_error(event, *args, **kwargs):
        logger.error(f'An error occurred in {event}: {args}', exc_info=True)

# Command error handler
@bot.event
async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
                await ctx.send("Command not found. Use `!help` to see available commands.")
        elif isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(f"Missing required argument: {error.param}")
        elif isinstance(error, commands.MissingPermissions):
                await ctx.send("You don't have permission to use this command.")
        else:
                logger.error(f'Command error in {ctx.command}: {error}', exc_info=True)
                await ctx.send("An error occurred while processing the command.")

# App command (slash command) error handler
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
        """Handle slash command errors"""
        error_name = error.__class__.__name__
        command_name = interaction.command.name if interaction.command else 'Unknown'

        logger.error(f'Slash command error in /{command_name}: {error_name} - {error}', exc_info=True)

        # Handle specific error types
        if isinstance(error, discord.app_commands.CommandInvokeError):
                # Unwrap the original error
                original_error = error.original
                if isinstance(original_error, discord.NotFound) and "Unknown interaction" in str(original_error):
                        logger.warning(f"Interaction timeout for /{command_name} - command took too long to respond")
                        return  # Can't respond to expired interaction
                elif isinstance(original_error, discord.HTTPException) and "already been acknowledged" in str(original_error):
                        logger.warning(f"Interaction already acknowledged for /{command_name}")
                        return  # Can't respond to already acknowledged interaction

        try:
                # Only try to send error message if we can verify interaction state
                if hasattr(interaction, 'response') and interaction.response:
                    if interaction.response.is_done():
                        # Interaction already responded to, try followup
                        try:
                            await interaction.followup.send("❌ An error occurred while processing the command.", ephemeral=True)
                        except discord.HTTPException as followup_error:
                            if "already been acknowledged" not in str(followup_error):
                                logger.error(f"Followup error for /{command_name}: {followup_error}")
                    else:
                        # Can still respond normally
                        await interaction.response.send_message("❌ An error occurred while processing the command.", ephemeral=True)
                else:
                    logger.warning(f"Could not access interaction response for /{command_name}")
        except discord.NotFound:
                # Interaction expired while trying to send error message
                logger.warning(f"Could not send error message - interaction for /{command_name} expired")
        except discord.HTTPException as e:
                if "already been acknowledged" in str(e):
                        logger.warning(f"Could not send error message - interaction for /{command_name} already acknowledged")
                else:
                        logger.error(f"HTTP error sending error message for /{command_name}: {e}")
        except Exception as follow_error:
                logger.error(f"Error sending error message for /{command_name}: {follow_error}")

@bot.tree.command(name="hello", description="Sends a greeting")
async def hello(interaction: discord.Interaction):
        """Simple hello command - responds immediately to avoid timeout"""
        try:
                # Respond immediately to avoid 3-second timeout
                await interaction.response.send_message(f"Hello, {interaction.user.mention}! How can I help?")
        except discord.NotFound:
                logger.warning("Hello command timed out - interaction expired")
        except Exception as e:
                logger.error(f"Error in hello command: {e}")
                if not interaction.response.is_done():
                        try:
                                await interaction.response.send_message("❌ Hello command failed", ephemeral=True)
                        except:
                                pass

# Graceful shutdown handler
def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        asyncio.create_task(shutdown())

async def shutdown():
        """Gracefully shutdown the bot"""
        logger.info("Shutting down bot...")
        await bot.close()
        logger.info("Bot shut down complete")

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Main function to run the bot
async def main():
        """Main function to start the bot"""
        try:
                token = os.getenv('DISCORD_TOKEN')
                if not token:
                        logger.error("DISCORD_TOKEN not found in environment variables")
                        sys.exit(1)

                # Start the bot
                logger.info("Starting bot...")
                await bot.start(token)

        except discord.LoginFailure:
                logger.error("Invalid Discord token provided")
                sys.exit(1)
        except Exception as e:
                logger.error(f"Failed to start bot: {e}", exc_info=True)
                sys.exit(1)

# Run the bot
if __name__ == "__main__":
        try:
                asyncio.run(main())
        except KeyboardInterrupt:
                logger.info("Bot stopped by user")
        except Exception as e:
                logger.error(f"Fatal error: {e}", exc_info=True)
                sys.exit(1)