import discord
from discord.ext import commands, tasks
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz

from sheets import load_google_sheet, parse_due_date
from button import ReminderView


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

        self.jobs = {}
        self.load_tasks()
        self.refresh_tasks.start()  

    def reschedule_task(self, task_dict):
        """This is used to reschedule the reminders when the user updated with a new due date"""
        task_name = task_dict["task"]

        # Cancel old job if it exists
        if task_name in self.jobs:
            old_job = self.jobs.pop(task_name)
            try:
                old_job.remove()
                print(f"[DEBUG] Removed old job for {task_name}")
            except Exception as e:
                print(f"[DEBUG] Failed to remove job for {task_name}: {e}")

        # Schedule new one
        reminder_time, is_second = self.get_reminder_time(task_dict)
        if not reminder_time:
            print(f"[WARNING] Could not reschedule {task_name} (no valid reminder time)")
            return

        task_dict["is_second_reminder"] = is_second
        job = self.scheduler.add_job(
            self.send_reminder,
            "date",
            run_date=reminder_time,
            args=[task_dict]
        )
        self.jobs[task_name] = job
        print(f"[DEBUG] Rescheduled reminder for {task_name} at {reminder_time}")

    def get_reminder_time(self, task):
        """Get the first or second reminder from the google sheet"""
        #Check if anything in filled in the status column
        try:
            if str(task.get("status", "")).strip().lower() not in ["", "done"]:
                status_time = parse_due_date(str(task["status"]).strip())
                return status_time, True
        except Exception as e: 
            print(f"[DEBUG] Failed to parse status date for task '{task['task']}': {e}")

        try:
            # Fallback to due_date: first reminder
            due_time = parse_due_date(str(task["due_date"]).strip())
            return due_time, False
        except Exception as e:
            print(f"[DEBUG] Failed to parse due date for task '{task['task']}': {e}")
            return None, False

    def load_tasks(self):
        """Load all tasks from the Google Sheet and schedule reminders"""
        df = load_google_sheet()
        for _, row in df.iterrows():
            task_dict = row.to_dict()

            reminder_time, is_second = self.get_reminder_time(task_dict)
            if not reminder_time:
                print(f"[WARNING] No valid reminder date found for task '{task_dict['task']}' — skipping.")
                continue 

            task_dict["is_second_reminder"] = is_second
            self.reschedule_task(task_dict)

    # Background refresher (every 5 minutes)
    @tasks.loop(minutes=5)
    async def refresh_tasks(self):
        print("[DEBUG] Refreshing tasks from Google Sheet...")
        self.load_tasks()

    async def send_reminder(self, task):
        """Send reminders to users through DM"""
        try:
            user = await self.bot.fetch_user(int(task["discord_id"]))
            await user.send(
                f"Reminder: Your task **{task['task']}** is due!",
                view=ReminderView(task, reminders_cog=self) 
            )
        except Exception as e:
            print(f"Failed to send reminder to {task['discord_id']}: {e}")
#build the command
    @app_commands.command(name="reminders", description="List all your upcoming task deadlines.")
    async def reminders(self, interaction: discord.Interaction):
        """Show upcoming reminders for the user who runs the command."""
        await interaction.response.defer(ephemeral=True)

        try:
            df = load_google_sheet()
        except Exception as e:
            print(f"[ERROR] Failed to load Google Sheet: {e}")
            await interaction.followup.send("Failed to load reminder", ephemeral=True)
            return

        user_tasks = df[df["discord_id"].astype(str).str.strip() == str(interaction.user.id)]
        if user_tasks.empty:
            await interaction.followup.send("You have no upcoming deadlines.", ephemeral=True)
            return
#show your upcoming deadlines
        embed = discord.Embed(title="Your Upcoming Deadlines", color=discord.Color.green())
        tz = pytz.timezone("US/Pacific") #Change to your timezone
        now = datetime.now(tz)

        has_upcoming = False
        for _, row in user_tasks.iterrows():
            task = row.to_dict()
            print(f"[DEBUG] Checking task: {task['task']} (due_date={task['due_date']}, status={task['status']})")

            try:
                reminder_time, _ = self.get_reminder_time(task)
                print(f"[DEBUG] Parsed reminder_time={reminder_time}, now={now}")

                if not reminder_time or reminder_time < now:
                    continue  

                has_upcoming = True
                field_value = f"Due Date: {task['due_date']}"
                if str(task.get("status", "")).strip():
                    field_value += f"\nStatus: {task['status']}"

                embed.add_field(name=task["task"], value=field_value, inline=False)
            except Exception as e:
                print(f"[DEBUG] Failed to process task '{task.get('task', 'unknown')}': {e}")
                continue

        if not has_upcoming:
            await interaction.followup.send("You have no upcoming deadlines.", ephemeral=True)
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        print("Reminder Cog loaded and active")


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))