import discord
import asyncio
from datetime import datetime, timedelta
from sheets import update_status, update_due_date


class ReminderView(discord.ui.View):
    """This class contains all the UI for the chatbot"""

    def __init__(self, task, reminders_cog=None):
        super().__init__(timeout=None)
        self.task = task
        self.reminders_cog = reminders_cog

    #The first button: task finished
    @discord.ui.button(label="Done", style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction,
                   button: discord.ui.Button):
        await interaction.response.send_message("Thanks, task marked as done!")
        update_status(self.task["discord_id"], self.task["task"], "Done")
        if self.reminders_cog: 
            self.reminders_cog.load_tasks()

    #The second button: new due date
    @discord.ui.button(label="New Due Date", style=discord.ButtonStyle.secondary)
    async def reschedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        # check if it's second reminder
        if self.task.get("is_second_reminder", False):
            await interaction.response.send_message(
                "No extensions allowed anymore, please communicate with Dr. Bar"
            )
            return
        # Ask for new due date
        await interaction.response.send_message(
            "Enter the new due date (DD-MM-YYYY HH:MM):"
        )
        def check(m):
            return m.author.id == interaction.user.id and m.channel == interaction.channel

        while True:
            try:
                msg = await interaction.client.wait_for("message", check=check, timeout=180)
                from sheets import parse_due_date

                try:
                    new_due_date = parse_due_date(msg.content.strip())

                    # Parse original due date from task 
                    original_due_date = parse_due_date(self.task["due_date"])

                    # Check if new due date is more than 3 days after original due date
                    max_allowed_date = original_due_date + timedelta(days=3)
                    if new_due_date > max_allowed_date:
                        await interaction.followup.send(
                            "You've exceeded the acceptable extension, please negotiate with Dr. Bar instead."
                        )
                        continue

                    # Update Google Sheet with new due date
                    formatted_date = new_due_date.strftime("%d-%m-%Y %H:%M")
                    update_status(self.task["discord_id"], self.task["task"], formatted_date)
                    await interaction.followup.send(f"Thanks, due date updated to {formatted_date}")
                    if self.reminders_cog:
                        updated_task = dict(self.task)
                        updated_task["status"] = formatted_date
                        self.reminders_cog.reschedule_task(updated_task)

                    break  
#If date entered is in wrong format
                except ValueError:
                    await interaction.followup.send(
                        "Sorry, invalid date format. Please follow the format DD-MM-YYYY HH:MM."
                    )

            except asyncio.TimeoutError:
                await interaction.followup.send("Sorry, you didn’t respond in time.")
                break
