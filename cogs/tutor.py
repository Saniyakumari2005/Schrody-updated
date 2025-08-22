import discord
from discord import app_commands
from discord.ext import commands, tasks
import db
import datetime
from learnlm import LearnLMTutor
from sessions import session_manager 

class Tutor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guest_participation_asked = set()  # Track users who have been asked about participation
        self.check_inactive_sessions.start()

    def get_user_display_name(self, user, guild):
        """Get user's display name (nickname if available, otherwise username)"""
        if guild:
            member = guild.get_member(user.id)
            if member and member.nick:
                return member.nick
            return member.display_name if member else user.display_name
        return user.display_name

    @app_commands.command(name="start_session", description="Start a tutoring session.")
    async def start_session(self, interaction: discord.Interaction):
        """Starts a tutoring session and logs the start time."""
        # Check if the command is being used in a DM
        if isinstance(interaction.channel, discord.DMChannel):
            await interaction.response.send_message(
                "❌ This command cannot be used in DMs. Please use it in a server channel where I can create threads.",
                ephemeral=True
            )
            return

        # Check if the channel supports threads
        if not hasattr(interaction.channel, 'create_thread'):
            await interaction.response.send_message(
                "❌ This command can only be used in channels that support threads (text channels).",
                ephemeral=True
            )
            return
            
        user = interaction.user
        existing_session = db.sessions_collection.find_one({"user_id": str(user.id), "active": True})

        if existing_session:
            await interaction.response.send_message(f"❌ {user.mention}, you already have an active session with Schrödy!", ephemeral=True)
            return

        # Check if we're in an existing Schrödy thread
        if isinstance(interaction.channel, discord.Thread):
            user_display_name = self.get_user_display_name(user, interaction.guild)
            expected_thread_name = f"Schrödy-{user_display_name}"

            if interaction.channel.name.startswith("Schrödy-"):
                # We're in an existing Schrody thread - ask for confirmation
                embed = discord.Embed(
                    title="⚠️ New Session Confirmation",
                    description=f"{user.mention}, you're trying to start a new session in an existing thread. This will:",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="What happens if you proceed:",
                    value="• Create a **new conversation** (previous context will be lost)\n• Create a **new thread** in the main channel\n• End any existing session context",
                    inline=False
                )
                embed.add_field(
                    name="Alternatives:",
                    value="• Use `/resume_session` to continue your existing conversation\n• Use `/ask` to continue in this thread if you have an active session",
                    inline=False
                )
                embed.set_footer(text="Use the command again in the main channel if you want to start fresh, or use /resume_session to continue.")

                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Use user's display name for thread name
        user_display_name = self.get_user_display_name(user, interaction.guild)

        # Check if we're in a thread, if so, get the parent channel
        if isinstance(interaction.channel, discord.Thread):
            parent_channel = interaction.channel.parent
            thread = await parent_channel.create_thread(name=f"Schrödy-{user_display_name}", type=discord.ChannelType.public_thread)
        else:
            thread = await interaction.channel.create_thread(name=f"Schrödy-{user_display_name}", type=discord.ChannelType.public_thread)

        # Create session using sessions.py system
        session = session_manager.create_session(thread)
        user_session = session.add_user(user)

        db.start_session(interaction.user.id, interaction.user.name, thread.id)

        # Create styled embed for session start
        embed = discord.Embed(
            title="📚 Tutoring Session Started",
            description=f"{user.mention}, Schrödy is here to assist you! Ask me anything.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🎯 Your Learning Environment:",
            value="This is your personalized tutoring space with Schrödy",
            inline=False
        )
        embed.add_field(
            name="👥 Multiuser Session:",
            value="Other users can join and participate as guests to learn together!",
            inline=False
        )
        embed.add_field(
            name="💡 Pro Tip:",
            value="Ask questions naturally - I'm here to help you understand concepts step by step!",
            inline=False
        )

        await thread.send(embed=embed)
        await interaction.response.send_message(f"📚 Tutoring session started, {interaction.user.mention}! I'll assist you in the thread I created.")

    @app_commands.command(name="ask", description="Ask Schrody a question.")
    async def ask(self, interaction: discord.Interaction, question: str):
        # Show thinking indicator immediately before deferring with user identification
        user_display_name = self.get_user_display_name(interaction.user, interaction.guild)
        thinking_message = await interaction.channel.send(f"🤔 Schrödy is thinking... (responding to {user_display_name})")

        # Defer the response to prevent timeout
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        user_int_id = interaction.user.id

        try:
            # Check if user has an active session
            existing_session = db.sessions_collection.find_one({"user_id": user_id, "active": True})

            if existing_session:
                # User has active session - check if we're in a tutoring thread
                if isinstance(interaction.channel, discord.Thread) and interaction.channel.name.startswith("Schrödy-"):
                    session = session_manager.get_session(interaction.channel.id)
                    if session:
                        user_session = session.get_user_session(user_int_id)
                        if user_session:
                            # Handle as active session owner
                            await self._handle_active_user_question(interaction, question, user_id, user_int_id, session, thinking_message)
                        else:
                            await thinking_message.delete()
                            await interaction.followup.send("❌ Please use this command in your tutoring thread or start a new session with `/start_session`.")
                    else:
                        await thinking_message.delete()
                        await interaction.followup.send("❌ Please use this command in your tutoring thread or start a new session with `/start_session`.")
                else:
                    await thinking_message.delete()
                    await interaction.followup.send("❌ Please use this command in your tutoring thread or start a new session with `/start_session`.")
            else:
                # User doesn't have active session - check if they're in someone else's thread
                if isinstance(interaction.channel, discord.Thread) and interaction.channel.name.startswith("Schrödy-"):
                    # They're in a tutoring thread - handle as guest
                    await self._handle_guest_user_question(interaction, question, user_id, user_int_id, thinking_message)
                else:
                    # Not in a tutoring thread and no active session
                    await thinking_message.delete()
                    embed = discord.Embed(
                        title="❌ No Active Session",
                        description="You don't have an active tutoring session.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="💡 What you can do:",
                        value="1️⃣ **Try resuming:** Use `/resume_session` if you had a previous session\n2️⃣ **Start fresh:** Use `/start_session` to begin a new conversation\n3️⃣ **Join a session:** Use this command in an existing Schrödy thread to participate as a guest",
                        inline=False
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await thinking_message.delete()
            print(f"Error in ask command: {e}")
            await interaction.followup.send("❌ An error occurred while processing your question. Please try again.", ephemeral=True)

    async def _handle_active_user_question(self, interaction, question, user_id, user_int_id, session, thinking_message):
        """Handle question from user with active session using sessions.py system."""
        try:
            # Update last activity time in database and reset warning flags
            db.sessions_collection.update_one(
                {"user_id": user_id, "active": True},
                {"$set": {
                    "last_activity": datetime.datetime.utcnow(),
                    "dm_warning_sent": False,
                    "thread_reminder_sent": False
                }}
            )

            # Process the message through the session system
            # Create a mock message object for the session system
            class MockMessage:
                def __init__(self, content, author, channel):
                    self.content = content
                    self.author = author
                    self.channel = channel

            mock_message = MockMessage(question, interaction.user, interaction.channel)

            # Let the session system handle the message processing
            await session.process_message(mock_message)

            # Delete the thinking message
            await thinking_message.delete()
        except Exception as e:
            await thinking_message.delete()
            print(f"Error handling active user question: {e}")
            await interaction.followup.send("❌ An error occurred while processing your question. Please try again.", ephemeral=True)

    async def _handle_guest_user_question(self, interaction, question, user_id, user_int_id, thinking_message):
        """Handle question from guest user."""
        try:
            thread_id = interaction.channel.id
            session = session_manager.get_session(thread_id)

            if not session:
                await thinking_message.delete()
                await interaction.followup.send("❌ This appears to be an inactive tutoring thread. Please start a new session with `/start_session`.")
                return

            # Ask about participation if not already asked
            if user_int_id not in self.guest_participation_asked:
                self.guest_participation_asked.add(user_int_id)

                # Create participation confirmation embed
                embed = discord.Embed(
                    title="🤝 Join Session as Guest?",
                    description=f"{interaction.user.mention}, you're about to participate in another user's tutoring session as a guest.",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="As a guest, you will:",
                    value="• Be able to ask questions and get responses\n• Have your conversation saved for context\n• Get suggestions to start your own session for personalized help\n• Participate in the shared learning environment",
                    inline=False
                )
                embed.add_field(
                    name="Note:",
                    value="This is a one-time confirmation. You can always start your own session later with `/start_session`.",
                    inline=False
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

            # Add user to session as guest
            guest_session = session.add_user(interaction.user)

            # Create a mock message object for the session system
            class MockMessage:
                def __init__(self, content, author, channel):
                    self.content = content
                    self.author = author
                    self.channel = channel

            mock_message = MockMessage(question, interaction.user, interaction.channel)

            # Let the session system handle the message processing
            await session.process_message(mock_message)

            # Delete the thinking message
            await thinking_message.delete()
        except Exception as e:
            await thinking_message.delete()
            print(f"Error handling guest user question: {e}")
            await interaction.followup.send("❌ An error occurred while processing your question. Please try again.", ephemeral=True)

    @app_commands.command(name="resume_session", description="Resume your tutoring session (works for both active and ended sessions).")
    async def resume_session(self, interaction: discord.Interaction):
        """Resume an existing tutoring session (both active and ended sessions)."""
        user = interaction.user
        user_id = str(user.id)

        try:
            # Check if user has an active session first
            existing_session = db.sessions_collection.find_one({"user_id": user_id, "active": True})

            # If no active session, check for any previous session (including ended ones)
            if not existing_session:
                # Look for the most recent session (active or ended)
                recent_session = db.sessions_collection.find_one(
                    {"user_id": user_id}, 
                    sort=[("start_time", -1)]
                )

                if not recent_session:
                    await interaction.response.send_message(
                        f"❌ {user.mention}, you don't have any previous sessions to resume. Use `/start_session` to begin a new one!", 
                        ephemeral=True
                    )
                    return

                # Reactivate the session if it was ended
                if not recent_session.get("active", False):
                    db.sessions_collection.update_one(
                        {"user_id": user_id, "_id": recent_session["_id"]},
                        {"$set": {
                            "active": True,
                            "last_activity": datetime.datetime.utcnow(),
                            "dm_warning_sent": False,
                            "thread_reminder_sent": False
                        }}
                    )
                    existing_session = recent_session

            # Try to find the existing thread
            thread_found = False
            user_display_name = self.get_user_display_name(user, interaction.guild)
            thread_name = f"Schrödy-{user_display_name}"

            # If we're already in the correct thread, just resume here
            if isinstance(interaction.channel, discord.Thread) and interaction.channel.name == thread_name:
                # Check if user is a member of this thread
                if any(member.id == user.id for member in interaction.channel.members):
                    # Create or get session using sessions.py system
                    session = session_manager.get_session(interaction.channel.id)
                    if not session:
                        session = session_manager.create_session(interaction.channel)

                    user_session = session.add_user(user)

                    # Update last activity time and reset warning flags
                    db.sessions_collection.update_one(
                        {"user_id": user_id, "active": True}, 
                        {"$set": {
                            "last_activity": datetime.datetime.utcnow(),
                            "dm_warning_sent": False,
                            "thread_reminder_sent": False
                        }}
                    )

                    await interaction.response.send_message(
                        f"✅ {user.mention}, your session has been resumed in this thread!", 
                        ephemeral=True
                    )

                    # Create styled embed for session resume
                    embed = discord.Embed(
                        title="🔄 Session Resumed",
                        description=f"{user.mention}, welcome back! Your session has been resumed.",
                        color=discord.Color.blue()
                    )
                    embed.add_field(
                        name="💬 Ready to Continue:",
                        value="Your conversation history is preserved - continue asking your questions!",
                        inline=False
                    )
                    embed.add_field(
                        name="👥 Multiuser Session:",
                        value="Other users can join and participate as guests to learn together!",
                        inline=False
                    )

                    await interaction.channel.send(embed=embed)
                    return

            # Search for the thread in the guild
            guild = interaction.guild if interaction.guild else None
            if guild:
                # First check active threads
                active_threads = await guild.active_threads()
                for thread in active_threads:
                    if thread.name == thread_name:
                        # Check if user is a member or try to add them
                        try:
                            if not any(member.id == user.id for member in thread.members):
                                await thread.add_user(user)

                            # Create or get session using sessions.py system
                            session = session_manager.get_session(thread.id)
                            if not session:
                                session = session_manager.create_session(thread)

                            user_session = session.add_user(user)

                            # Update last activity time and reset warning flags
                            db.sessions_collection.update_one(
                                {"user_id": user_id, "active": True}, 
                                {"$set": {
                                    "last_activity": datetime.datetime.utcnow(),
                                    "dm_warning_sent": False,
                                    "thread_reminder_sent": False
                                }}
                            )

                            await interaction.response.send_message(
                                f"✅ {user.mention}, your session has been resumed in {thread.mention}!", 
                                ephemeral=True
                            )

                            # Create styled embed for session resume
                            embed = discord.Embed(
                                title="🔄 Session Resumed",
                                description=f"{user.mention}, welcome back! Your session has been resumed.",
                                color=discord.Color.blue()
                            )
                            embed.add_field(
                                name="💬 Ready to Continue:",
                                value="Your conversation history is preserved - continue asking your questions!",
                                inline=False
                            )
                            embed.add_field(
                                name="👥 Multiuser Session:",
                                value="Other users can join and participate as guests to learn together!",
                                inline=False
                            )

                            await thread.send(embed=embed)
                            thread_found = True
                            break
                        except discord.Forbidden:
                            continue

                # If not found in active threads, check archived threads
                if not thread_found:
                    async for thread in guild.archived_threads(limit=100):
                        if thread.name == thread_name:
                            try:
                                # Try to unarchive and add user
                                await thread.edit(archived=False)
                                if not any(member.id == user.id for member in thread.members):
                                    await thread.add_user(user)

                                # Create or get session using sessions.py system
                                session = session_manager.get_session(thread.id)
                                if not session:
                                    session = session_manager.create_session(thread)

                                user_session = session.add_user(user)

                                # Update last activity time and reset warning flags
                                db.sessions_collection.update_one(
                                    {"user_id": user_id, "active": True}, 
                                    {"$set": {
                                        "last_activity": datetime.datetime.utcnow(),
                                        "dm_warning_sent": False,
                                        "thread_reminder_sent": False
                                    }}
                                )

                                await interaction.response.send_message(
                                    f"✅ {user.mention}, your session has been resumed in {thread.mention}!", 
                                    ephemeral=True
                                )

                                # Create styled embed for session resume from archive
                                embed = discord.Embed(
                                    title="🔄 Session Resumed",
                                    description=f"{user.mention}, welcome back! Your session has been resumed from archive.",
                                    color=discord.Color.blue()
                                )
                                embed.add_field(
                                    name="💬 Ready to Continue:",
                                    value="Your conversation history is preserved - continue asking your questions!",
                                    inline=False
                                )
                                embed.add_field(
                                    name="👥 Multiuser Session:",
                                    value="Other users can join and participate as guests to learn together!",
                                    inline=False
                                )

                                await thread.send(embed=embed)
                                thread_found = True
                                break
                            except discord.Forbidden:
                                continue
                            except Exception as e:
                                print(f"Error unarchiving thread: {e}")
                                continue

            if not thread_found:
                # Create a new thread since the old one wasn't found
                user_display_name = self.get_user_display_name(user, interaction.guild)

                # Check if we're in a thread, if so, get the parent channel
                if isinstance(interaction.channel, discord.Thread):
                    parent_channel = interaction.channel.parent
                    thread = await parent_channel.create_thread(name=f"Schrödy-{user_display_name}", type=discord.ChannelType.public_thread)
                else:
                    thread = await interaction.channel.create_thread(name=f"Schrödy-{user_display_name}", type=discord.ChannelType.public_thread)

                # Create session using sessions.py system
                session = session_manager.create_session(thread)
                user_session = session.add_user(user)

                # Update last activity time and reset warning flags
                db.sessions_collection.update_one(
                    {"user_id": user_id, "active": True}, 
                    {"$set": {
                        "last_activity": datetime.datetime.utcnow(),
                        "dm_warning_sent": False,
                        "thread_reminder_sent": False
                    }}
                )

                await interaction.response.send_message(
                    f"✅ {user.mention}, your session has been resumed in a new thread since the previous one wasn't found!", 
                    ephemeral=True
                )

                # Create styled embed for session resume in new thread
                embed = discord.Embed(
                    title="🔄 Session Resumed",
                    description=f"{user.mention}, welcome back! Your session has been resumed in a new thread.",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="💾 History Preserved:",
                    value="Your conversation history has been preserved - continue asking your questions!",
                    inline=False
                )
                embed.add_field(
                    name="👥 Multiuser Session:",
                    value="Other users can join and participate as guests to learn together!",
                    inline=False
                )
                embed.add_field(
                    name="🆕 New Thread:",
                    value="A new thread was created since the previous one wasn't found.",
                    inline=False
                )

                await thread.send(embed=embed)

        except Exception as e:
            print(f"Error in resume_session: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ {user.mention}, an error occurred while resuming your session. Please try again or start a new session.", 
                    ephemeral=True
                )

    @app_commands.command(name="end_session", description="End the tutoring session.")
    async def end_session(self, interaction: discord.Interaction):
        """Ends a tutoring session and asks for feedback."""
        if isinstance(interaction.channel, discord.Thread):
            session = session_manager.get_session(interaction.channel.id)
            if session:
                user_session = session.get_user_session(interaction.user.id)
                if user_session:
                    await interaction.response.send_message("Session ended successfully.", ephemeral=True)
                    # End the user's individual session
                    await session.end_user_session(interaction.user)

                    # Update database with thread_id
                    db.end_session(interaction.user.id, interaction.channel.id)

                    # Create styled embed for session end
                    embed = discord.Embed(
                        title="📚 Session Ended",
                        description=f"{interaction.user.mention}, your tutoring session has ended successfully.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="💬 Feedback Request:",
                        value="Please rate your experience with `/feedback <1-5>` to help us improve!",
                        inline=False
                    )
                    embed.add_field(
                        name="📈 Session Summary:",
                        value="Your individual session has been completed and saved for future reference.",
                        inline=False
                    )
                    embed.add_field(
                        name="🔄 Next Time:",
                        value="Use `/start_session` to begin a new session or `/resume_session` to continue where you left off.",
                        inline=False
                    )
                    await interaction.channel.send(embed=embed)                   

                    # Only remove the entire session if no other users are active
                    if len(session.get_active_users()) == 0:
                        session_manager.end_session(interaction.channel.id)

                else:
                    await interaction.response.send_message(
                        "❌ You don't have an active session in this thread.", 
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "❌ No active session found in this thread.", 
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "❌ This command must be used in a tutoring thread.", 
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages in tutoring threads and respond automatically."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Check if message is in a tutoring thread
        if not (isinstance(message.channel, discord.Thread) and message.channel.name.startswith("Schrödy-")):
            return

        # Update last activity time for any active session in this thread and reset warning flags
        user_id = str(message.author.id)
        db.sessions_collection.update_one(
            {"user_id": user_id, "active": True},
            {"$set": {
                "last_activity": datetime.datetime.utcnow(),
                "dm_warning_sent": False,
                "thread_reminder_sent": False
            }}
        )

        # Show thinking indicator with user identification
        user_display_name = self.get_user_display_name(message.author, message.guild)
        thinking_message = await message.channel.send(f"🤔 Schrödy is thinking... (responding to {user_display_name})")

        try:
            # Get or create session using sessions.py system
            session = session_manager.get_session(message.channel.id)
            if not session:
                # This might be an old thread, create a new session
                session = session_manager.create_session(message.channel)

            # Add user to session if not already added
            session.add_user(message.author)

            # Let the session system handle the message
            await session.process_message(message)

            # Delete the thinking message
            await thinking_message.delete()
        except Exception as e:
            await thinking_message.delete()
            print(f"Error in on_message: {e}")

    @tasks.loop(minutes=5)
    async def check_inactive_sessions(self):
        """Check for inactive sessions and send reminders/close as needed."""
        try:
            # Clean up inactive sessions across all session managers
            session_manager.cleanup_inactive_sessions()

            # Your existing database cleanup logic here
            now = datetime.datetime.utcnow()
            for session in db.sessions_collection.find({"active": True}):
                try:
                    time_since_activity = now - session.get("last_activity", session["start_time"])
                    user_id = session["user_id"]

                    # 30 minutes - close session
                    if time_since_activity >= datetime.timedelta(minutes=30):
                        db.end_session(user_id)
                        try:
                            user = await self.bot.fetch_user(int(user_id))
                            await user.send("⏳ Your tutoring session has ended due to inactivity. Please provide feedback with `/feedback <1-5>`.")
                        except (discord.NotFound, discord.Forbidden):
                            pass

                    # 15 minutes - send DM warning (only if not already sent)
                    elif time_since_activity >= datetime.timedelta(minutes=15) and not session.get("dm_warning_sent", False):
                        try:
                            user = await self.bot.fetch_user(int(user_id))
                            embed = discord.Embed(
                                title="⚠️ Inactivity Warning",
                                description="Your tutoring session will close in 15 minutes due to inactivity.",
                                color=discord.Color.orange()
                            )
                            embed.add_field(
                                name="💡 Keep your session active:",
                                value="Send a message in your session thread to continue learning!",
                                inline=False
                            )
                            await user.send(embed=embed)
                            db.sessions_collection.update_one(
                                {"user_id": user_id, "active": True},
                                {"$set": {"dm_warning_sent": True}}
                            )
                        except (discord.NotFound, discord.Forbidden):
                            pass

                    # 5 minutes - send thread reminder (only if not already sent)
                    elif time_since_activity >= datetime.timedelta(minutes=5) and not session.get("thread_reminder_sent", False):
                        # Find the thread through session manager
                        for thread_id, tutoring_session in session_manager.sessions.items():
                            user_session = tutoring_session.get_user_session(int(user_id))
                            if user_session:
                                try:
                                    embed = discord.Embed(
                                        title="💤 Are you still there?",
                                        description=f"<@{user_id}>, you've been inactive for 5 minutes.",
                                        color=discord.Color.yellow()
                                    )
                                    embed.add_field(
                                        name="⏰ Session will close in:",
                                        value="25 minutes if no activity is detected",
                                        inline=False
                                    )
                                    embed.add_field(
                                        name="💬 To continue:",
                                        value="Just send any message or question to keep your session active!",
                                        inline=False
                                    )
                                    await tutoring_session.thread.send(embed=embed)
                                    db.sessions_collection.update_one(
                                        {"user_id": user_id, "active": True},
                                        {"$set": {"thread_reminder_sent": True}}
                                    )
                                    break
                                except discord.NotFound:
                                    pass

                except Exception as e:
                    print(f"Error processing session for user {session.get('user_id', 'unknown')}: {e}")
                    continue

        except Exception as e:
            print(f"Error in check_inactive_sessions: {e}")

    @check_inactive_sessions.before_loop
    async def before_check_inactive_sessions(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Tutor(bot))