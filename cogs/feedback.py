import discord
from discord import app_commands
from discord.ext import commands, tasks
import db
import datetime

class Feedback(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.remind_feedback.start()  # Disabled to prevent multiple DM reminders

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

    @app_commands.command(name="pending_feedback", description="List users who haven't given feedback.")
    async def pending_feedback(self, interaction: discord.Interaction):
        """Lists users who haven't submitted feedback."""
        pending_users = db.get_pending_feedback()
        if len(list(pending_users)) == 0:
            await interaction.response.send_message("✅ Everyone has submitted feedback!")
            return

        user_list = "\n".join([user["username"] for user in pending_users])
        await interaction.response.send_message(f"🚨 Users who haven't submitted feedback:\n```{user_list}```")

    @tasks.loop(hours=12)
    async def remind_feedback(self):
        """Reminds users to submit feedback every 12 hours."""
        for session in db.get_pending_feedback():
            # Check if we've already sent a reminder for this session
            if not session.get("reminder_sent", False):
                try:
                    user = await self.bot.fetch_user(int(session["user_id"]))
                    await user.send("🔔 Reminder: Schrödy is waiting for your feedback! Please use `/feedback <1-5>`.")

                    # Mark that we've sent a reminder for this session
                    db.sessions_collection.update_one(
                        {"_id": session["_id"]}, 
                        {"$set": {"reminder_sent": True}}
                    )
                except Exception as e:
                    print(f"Failed to send feedback reminder to user {session['user_id']}: {e}")

async def setup(bot):
    await bot.add_cog(Feedback(bot))