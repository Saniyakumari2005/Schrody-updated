import discord
from discord import app_commands
from discord.ext import commands, tasks
import db
import datetime

class Feedback(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.remind_feedback.start()  

    @app_commands.command(name="feedback", description="Submit feedback (1-5).")
    async def feedback(self, interaction: discord.Interaction, rating: int):
        """Logs user feedback."""
        try:
            if rating < 1 or rating > 5:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Please provide a rating between 1 and 5.")
                return

            db.log_feedback(interaction.user.id, rating)
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Thanks for your feedback!")
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Error processing feedback. Please try again.")
            print(f"Error in feedback command: {e}")

    
    @app_commands.command(name="pending_feedback", description="Show count of users with pending feedback.")
    @app_commands.default_permissions(administrator=True)
    async def pending_feedback(self, interaction: discord.Interaction):
        """Shows how many users haven't submitted feedback."""
        pending = db.get_pending_feedback()
        count = len(pending)
        if count == 0:
            await interaction.response.send_message("✅ Everyone has submitted feedback!", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"🚨 **{count}** user(s) have not submitted feedback yet.",
                ephemeral=True
            )
            
    @tasks.loop(hours=1)
    async def remind_feedback(self):
        """Reminds users to submit feedback every hour."""
        for session in db.get_pending_feedback():
            if not session.get("reminder_sent", False):
                anonymous_user_id = session.get("anonymous_user_id")
                try:
                    if not anonymous_user_id:
                        continue

                    # Reverse-look up the real Discord ID
                    discord_id = db.get_discord_id_from_anonymous(anonymous_user_id)
                    if not discord_id:
                        print(f"Could not find Discord ID for anonymous user {anonymous_user_id}, skipping reminder")
                        continue

                    user = await self.bot.fetch_user(int(discord_id))
                    await user.send("🔔 Reminder: Schrödy is waiting for your feedback! Please use `/feedback <1-5>`.")

                    db.sessions_collection.update_one(
                        {"_id": session["_id"]},
                        {"$set": {"reminder_sent": True}}
                    )
                except discord.Forbidden:
                    # User has DMs disabled — mark as reminded to stop retrying
                    print(f"Cannot DM user {anonymous_user_id} — DMs likely disabled")
                    db.sessions_collection.update_one(
                        {"_id": session["_id"]},
                        {"$set": {"reminder_sent": True}}
                    )
                except Exception as e:
                    print(f"Failed to send feedback reminder: {e}")
                    
    @remind_feedback.before_loop
    async def before_remind_feedback(self):
        await self.bot.wait_until_ready()
        
async def setup(bot):
    await bot.add_cog(Feedback(bot))