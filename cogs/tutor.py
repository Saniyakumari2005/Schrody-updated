import discord
from discord import app_commands
from discord.ext import commands, tasks
import db
import datetime
from learnlm import LearnLMTutor
from sessions import session_manager
import asyncio

class ConsentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.consent = None

    @discord.ui.button(label="Yes, I Agree", style=discord.ButtonStyle.success)
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.consent = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="No, I Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.consent = False
        self.stop()
        await interaction.response.defer()

class Tutor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guest_participation_asked = set()
        self._consent_warned_users = set()
        self.check_inactive_sessions.start()
        self.private_thread_channels = set() 

        # Message deduplication - prevents Discord from sending same message twice
        self._message_processing_cache = {} 
        self._cache_cleanup_counter = 0
        self._global_lock = asyncio.Lock()

        # LearnLM tutor instances per session
        self._tutor_instances = {}

        # Set bot user ID in session manager for better bot detection
        if hasattr(self.bot, 'user') and self.bot.user:
            session_manager.set_bot_user_id(self.bot.user.id)

    def get_or_create_tutor(self, session_id: str) -> LearnLMTutor:
        """Get or create a LearnLM tutor instance for a session."""
        if session_id not in self._tutor_instances:
            self._tutor_instances[session_id] = LearnLMTutor(session_id=f"discord_{session_id}")
        return self._tutor_instances[session_id]

    def get_user_display_name(self, user, guild):
        """Get user's display name (nickname if available, otherwise username)"""
        if guild:
            member = guild.get_member(user.id)
            if member and member.nick:
                return member.nick
            return member.display_name if member else user.display_name
        return user.display_name

    async def find_or_create_user_thread(self, interaction, user_display_name):
        """Find existing thread for user or create a new one with appropriate privacy settings."""
        guild = interaction.guild
        thread_name = f"Schrödy-{user_display_name}"

        # Search for existing thread in active threads
        try:
            active_threads = await guild.active_threads()
            for thread in active_threads:
                if thread.name == thread_name:
                    return thread
        except Exception as e:
            print(f"Warning: Could not fetch active threads: {e}")

        # Search in archived threads within the current channel
        try:
            channel = interaction.channel
            if isinstance(channel, discord.Thread):
                channel = channel.parent
            if isinstance(channel, discord.TextChannel):
                async for thread in channel.archived_threads(limit=100):
                    if thread.name == thread_name:
                        try:
                            await thread.edit(archived=False)
                            return thread
                        except discord.Forbidden:
                            continue
                        except Exception as e:
                            print(f"Error unarchiving thread: {e}")
                            continue
        except Exception as e:
            print(f"Warning: Could not search archived threads: {e}")

        # Determine thread type based on channel configuration
        channel = interaction.channel
        if channel is None:
            raise ValueError("Cannot create threads without a channel")
        channel_id = channel.id
        if isinstance(channel, discord.Thread):
            if channel.parent is None:
                raise ValueError("Thread has no parent channel")
            channel_id = channel.parent.id

        # Check if this channel is configured for private threads
        is_private = channel_id in self.private_thread_channels
        thread_type = discord.ChannelType.private_thread if is_private else discord.ChannelType.public_thread

        # Create new thread if none found
        if isinstance(interaction.channel, discord.Thread):
            parent_channel = interaction.channel.parent
            if not isinstance(parent_channel, discord.TextChannel):
                raise ValueError("Parent channel is not a text channel")
            thread = await parent_channel.create_thread(
                name=thread_name, 
                type=thread_type
            )
        elif isinstance(interaction.channel, discord.TextChannel):
            thread = await interaction.channel.create_thread(
                name=thread_name, 
                type=thread_type
            )
        else:
            raise ValueError("Cannot create threads in this type of channel")

        return thread

    @app_commands.command(name="start_session", description="Start or resume your tutoring session in your personal thread.")
    async def start_session(self, interaction: discord.Interaction):
        """Starts or resumes a tutoring session in the user's personal thread."""
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
            
        # Consent Check
        anonymous_user_id_check = db._get_or_create_anonymous_id(str(interaction.user.id), interaction.user.name)
        existing_user_consent = db.users_collection.find_one({"anonymous_id": anonymous_user_id_check})

        if not existing_user_consent or existing_user_consent.get("consent") is not True:
            consent_embed = discord.Embed(
                title="📋 Terms & Conditions",
                description=(
                    "Before using this tutoring bot, please read and accept our [Data Privacy Statement](https://drive.google.com/file/d/1yQUrUAg1JUoYnhCDBFEY78j6jIIGWACm/view?usp=sharing).\n\n"
                    "**By clicking Yes, you agree to:**\n"
                    "- Your messages being stored for session continuity\n"
                    "- Anonymous usage data being used for improvements and educational research\n"
                    "- Abiding by the server's rules during tutoring sessions\n\n"
                    "You must accept to use the tutoring bot."
                ),
                color=discord.Color.blurple()
            )
            view = ConsentView()
            await interaction.response.send_message(embed=consent_embed, view=view, ephemeral=True)
            await view.wait()

            if view.consent is True:
                db.users_collection.update_one(
                    {"anonymous_id": anonymous_user_id_check},
                    {"$set": {"consent": True, "consent_timestamp": datetime.datetime.utcnow()}},
                    upsert=True
                )
            elif view.consent is False:
                declined_embed = discord.Embed(
                    title="📋 Terms & Conditions",
                    description=(
                        "Before using this tutoring bot, please read and accept our [Data Privacy Statement](https://drive.google.com/file/d/1yQUrUAg1JUoYnhCDBFEY78j6jIIGWACm/view?usp=sharing).\n\n"
                        "**By clicking Yes, you agree to:**\n"
                        "- Your messages being stored for session continuity\n"
                        "- Anonymous usage data being used for improvements and educational research\n"
                        "- Abiding by the server's rules during tutoring sessions\n\n"
                        "You must accept to use the tutoring bot."
                    ),
                    color=discord.Color.red()
                )
                declined_embed.set_footer(text="You declined. Use /start_session again to be prompted.")
                await interaction.edit_original_response(embed=declined_embed, view=None)
                return
            else:
                await interaction.edit_original_response(
                    content="⏰ The consent prompt timed out. Please use `/start_session` again.",
                    embed=None, view=None
                )
                return
        
        # End Consent Check - defer if we haven't responded yet
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        user = interaction.user
        user_display_name = self.get_user_display_name(user, interaction.guild)
        # Get anonymous user ID for database operations
        anonymous_user_id = db._get_or_create_anonymous_id(str(user.id), user.name)
        existing_session = db.sessions_collection.find_one({"anonymous_user_id": anonymous_user_id, "active": True})

        # Find or create the user's personal thread
        try:
            thread = await self.find_or_create_user_thread(interaction, user_display_name)

            # Add user to thread if not already a member
            if not any(member.id == user.id for member in thread.members):
                await thread.add_user(user)

            # Create or get session using sessions.py system
            session = session_manager.get_session(thread.id)
            if not session:
                session = session_manager.create_session(thread)

            user_session = session.add_user(user)

            if existing_session:
                # Resume existing session
                db.sessions_collection.update_one(
                    {"anonymous_user_id": anonymous_user_id, "active": True}, 
                    {"$set": {
                        "last_activity": datetime.datetime.utcnow(),
                        "dm_warning_sent": False,
                        "thread_reminder_sent": False,
                        "second_reminder_sent": False
                    }}
                )

                embed = discord.Embed(
                    title="🔄 Session Resumed",
                    description=f"{user.mention}, welcome back to your personal tutoring space!",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="💬 Ready to Continue:",
                    value="Your conversation history is preserved - just type your questions naturally!",
                    inline=False
                )
                embed.add_field(
                    name="👥 Multiuser Session:",
                    value="Other users can join and participate as guests to learn together!",
                    inline=False
                )

                await interaction.followup.send(
                    f"✅ {user.mention}, your session has been resumed in {thread.mention}!",
                    ephemeral=True
                )
                await thread.send(embed=embed)
            else:
                # Start new session
                db.start_session(user.id, user.name, thread.id)

                embed = discord.Embed(
                    title="📚 Tutoring Session Started",
                    description=f"{user.mention}, welcome to your personal tutoring space with Schrödy!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="🎯 Your Learning Environment:",
                    value="This is your personalized tutoring space - just type your questions naturally!",
                    inline=False
                )
                embed.add_field(
                    name="👥 Multiuser Session:",
                    value="Other users can join and participate as guests to learn together!",
                    inline=False
                )
                embed.add_field(
                    name="💡 Pro Tip:",
                    value="No commands needed - I'm here to help you understand concepts step by step!",
                    inline=False
                )

                await interaction.followup.send(
                    f"📚 Tutoring session started in {thread.mention}!",
                    ephemeral=True
                )
                await thread.send(embed=embed)

        except Exception as e:
            import traceback
            print(f"Error in start_session: {e}")
            print(traceback.format_exc())
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ An error occurred while setting up your session. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ An error occurred while setting up your session. Please try again.",
                        ephemeral=True
                    )
            except Exception as follow_error:
                print(f"Could not send error message: {follow_error}")

    @app_commands.command(name="start_new_session", description="Start a completely new tutoring session (clears conversation history).")
    async def start_new_session(self, interaction: discord.Interaction):
        """Starts a completely new tutoring session, clearing previous conversation history."""
        # Check if user has administrator permissions
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command is restricted to administrators only.", ephemeral=True)
            return

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
        user_display_name = self.get_user_display_name(user, interaction.guild)

        try:
            # Find or create the user's personal thread
            thread = await self.find_or_create_user_thread(interaction, user_display_name)

            # Add user to thread if not already a member
            if not any(member.id == user.id for member in thread.members):
                await thread.add_user(user)

            # End any existing session
            # Get anonymous user ID for database operations
            anonymous_user_id = db._get_or_create_anonymous_id(str(user.id), user.name)
            existing_session = db.sessions_collection.find_one({"anonymous_user_id": anonymous_user_id, "active": True})
            if existing_session:
                db.end_session(user.id, thread.id)

            # Clear session from session manager to start fresh
            if session_manager.get_session(thread.id):
                await session_manager.end_session(thread.id)

            # Create completely new session
            session = session_manager.create_session(thread)
            user_session = session.add_user(user)

            # Start new database session
            db.start_session(user.id, user.name, thread.id)

            embed = discord.Embed(
                title="🆕 New Tutoring Session Started",
                description=f"{user.mention}, a fresh tutoring session has been started!",
                color=discord.Color.green()
            )
            embed.add_field(
                name="🔄 Fresh Start:",
                value="Your conversation history has been cleared for a completely new learning experience.",
                inline=False
            )
            embed.add_field(
                name="🎯 Your Learning Environment:",
                value="This is your personalized tutoring space - just type your questions naturally!",
                inline=False
            )
            embed.add_field(
                name="👥 Multiuser Session:",
                value="Other users can join and participate as guests to learn together!",
                inline=False
            )

            await interaction.response.send_message(
                f"🆕 New tutoring session started in {thread.mention}!",
                ephemeral=True
            )
            await thread.send(embed=embed)

        except Exception as e:
            print(f"Error in start_new_session: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred while starting your new session. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ An error occurred while starting your new session. Please try again.",
                        ephemeral=True
                    )
            except Exception as follow_error:
                print(f"Could not send error message: {follow_error}")

    @app_commands.command(name="resume_session", description="Resume your tutoring session (works for both active and ended sessions).")
    async def resume_session(self, interaction: discord.Interaction):
        """Resume an existing tutoring session (both active and ended sessions)."""
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        user_id = str(user.id)
        user_display_name = self.get_user_display_name(user, interaction.guild)

        try:
            # Get anonymous user ID for database operations
            anonymous_user_id = db._get_or_create_anonymous_id(user_id, user.name)

            # Check if user has any session (active or ended)
            recent_session = db.sessions_collection.find_one(
                {"anonymous_user_id": anonymous_user_id}, 
                sort=[("start_time", -1)]
            )

            if not recent_session:
                await interaction.followup.send(
                    f"❌ {user.mention}, you don't have any previous sessions to resume. Use `/start_session` to begin!", 
                    ephemeral=True
                )
                return

            # Find the user's personal thread
            thread = await self.find_or_create_user_thread(interaction, user_display_name)

            # Add user to thread if not already a member
            if not any(member.id == user.id for member in thread.members):
                await thread.add_user(user)

            # Reactivate the session if it was ended
            if not recent_session.get("active", False):
                db.sessions_collection.update_one(
                    {"anonymous_user_id": anonymous_user_id, "_id": recent_session["_id"]},
                    {"$set": {
                        "active": True,
                        "last_activity": datetime.datetime.utcnow(),
                        "dm_warning_sent": False,
                        "thread_reminder_sent": False,
                        "second_reminder_sent": False
                    }}
                )

            # Create or get session using sessions.py system
            session = session_manager.get_session(thread.id)
            if not session:
                session = session_manager.create_session(thread)

            user_session = session.add_user(user)

            # Update last activity time and reset warning flags
            db.sessions_collection.update_one(
                {"anonymous_user_id": anonymous_user_id, "active": True}, 
                {"$set": {
                    "last_activity": datetime.datetime.utcnow(),
                    "dm_warning_sent": False,
                    "thread_reminder_sent": False,
                    "second_reminder_sent": False
                }}
            )

            embed = discord.Embed(
                title="🔄 Session Resumed",
                description=f"{user.mention}, welcome back to your personal tutoring space!",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="💬 Ready to Continue:",
                value="Your conversation history is preserved - just type your questions naturally!",
                inline=False
            )
            embed.add_field(
                name="👥 Multiuser Session:",
                value="Other users can join and participate as guests to learn together!",
                inline=False
            )

            await interaction.followup.send(
                f"✅ {user.mention}, your session has been resumed in {thread.mention}!", 
                ephemeral=True
            )
            await thread.send(embed=embed)

        except Exception as e:
            print(f"Error in resume_session: {e}")
            try:
                await interaction.followup.send(
                    f"❌ {user.mention}, an error occurred while resuming your session. Please try again.", 
                    ephemeral=True
                )
            except Exception:
                pass

    @app_commands.command(name="end_session", description="End the tutoring session.")
    async def end_session(self, interaction: discord.Interaction):
        """Ends a tutoring session and asks for feedback."""
        try:
            if isinstance(interaction.channel, discord.Thread):
                session = session_manager.get_session(interaction.channel.id)
                if session:
                    user_session = session.get_user_session(interaction.user.id)
                    if user_session:
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
                            value="Your session has been completed and saved for future reference.",
                            inline=False
                        )
                        embed.add_field(
                            name="🔄 Next Time:",
                            value="Use `/start_session` to resume in your personal thread.",
                            inline=False
                        )

                        await interaction.response.send_message(embed=embed)

                        # End the user's individual session
                        await session.end_user_session(interaction.user)
                        db.end_session(interaction.user.id, interaction.channel.id)

                        # Only remove the entire session if no other users are active
                        if len(session.get_active_users()) == 0:
                            await session_manager.end_session(interaction.channel.id)

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
        except discord.HTTPException as e:
            print(f"Error in end_session: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ An error occurred while ending your session. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ An error occurred while ending your session. Please try again.",
                        ephemeral=True
                    )
            except:
                pass

    @app_commands.command(name="toggle_private_threads", description="Toggle private thread creation for this channel")
    @app_commands.default_permissions(administrator=True)
    async def toggle_private_threads(self, interaction: discord.Interaction):
        """Toggle whether this channel creates private or public threads."""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command is restricted to administrators only.", ephemeral=True)
            return

        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("❌ Could not determine the channel.", ephemeral=True)
            return

        channel_id = channel.id

        if channel_id in self.private_thread_channels:
            self.private_thread_channels.remove(channel_id)
            new_type = "**public**"
            emoji = "🌐"
        else:
            self.private_thread_channels.add(channel_id)
            new_type = "**private**"
            emoji = "🔒"

        channel_mention = getattr(channel, 'mention', f"#{channel_id}")
        await interaction.response.send_message(
            f"{emoji} {channel_mention} will now create {new_type} threads for tutoring sessions.",
            ephemeral=True
        )

    @app_commands.command(name="thread_status", description="Check if this channel creates private or public threads")
    @app_commands.default_permissions(administrator=True) 
    async def thread_status(self, interaction: discord.Interaction):
        """Check the current thread creation setting for this channel."""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command is restricted to administrators only.", ephemeral=True)
            return

        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("❌ Could not determine the channel.", ephemeral=True)
            return

        channel_id = channel.id

        if channel_id in self.private_thread_channels:
            status = "🔒 **Private threads**"
            description = "Only thread participants can see the conversation"
        else:
            status = "🌐 **Public threads** (default)"
            description = "All server members can see the threads"

        channel_name = getattr(channel, 'name', f"Channel {channel_id}")
        embed = discord.Embed(
            title=f"Thread Setting for {channel_name}",
            description=f"{status}\n\n{description}",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages in tutoring threads with comprehensive duplicate prevention."""

        # IMMEDIATE: Complete bot detection (must be first)
        if (message.author.bot or 
            (hasattr(self.bot, 'user') and self.bot.user and message.author.id == self.bot.user.id) or
           
            message.webhook_id is not None):
            return

        # SECOND: Basic validation
        if (not message.content or 
            not message.content.strip() or
            not isinstance(message.channel, discord.Thread) or
            not message.channel.name.startswith("Schrödy-") or
            message.content.startswith('/') or
            len(message.content) > 1500):
            return

        # THIRD: Content filtering for bot-like messages
        content_lower = message.content.lower()
        if ("🤔 schrödy is thinking" in content_lower or
            message.content.startswith('🤔') or
            "schrödy is thinking" in content_lower):
            return

        # FOURTH: CRITICAL - Atomic message deduplication
        import time
        current_time = time.time()

        unique_key = f"{message.id}_{message.author.id}_{hash(message.content)}"

        async with self._global_lock:
            if unique_key in self._message_processing_cache or message.id in self._message_processing_cache:
                return

            self._message_processing_cache[message.id] = current_time
            self._message_processing_cache[unique_key] = current_time

        try:
            user_id = str(message.author.id)
            user_int_id = message.author.id
            anonymous_user_id = db._get_or_create_anonymous_id(user_id, str(message.author))

            # Check consent before processing - users must accept T&C via /start_session
            user_record = db.users_collection.find_one({"anonymous_id": anonymous_user_id})
            if not user_record or user_record.get("consent") is not True:
                if user_int_id not in self._consent_warned_users:
                    self._consent_warned_users.add(user_int_id)
                    await message.channel.send(
                        f"{message.author.mention} You need to accept the Terms & Conditions first. "
                        f"Please use `/start_session` to get started.",
                        delete_after=15
                    )
                return

            existing_session = db.sessions_collection.find_one({"anonymous_user_id": anonymous_user_id, "active": True})

            # Register user in DB if they don't have an active session (guest)
            if not existing_session:
                db.start_session(message.author.id, message.author.name, message.channel.id)
                existing_session = db.sessions_collection.find_one(
                    {"anonymous_user_id": anonymous_user_id, "active": True}
                )

                if user_int_id not in self.guest_participation_asked:
                    self.guest_participation_asked.add(user_int_id)
                    embed = discord.Embed(
                        title="🤝 Welcome to the Session!",
                        description=f"{message.author.mention}, you've joined this tutoring session as a participant.",
                        color=discord.Color.blue()
                    )
                    embed.add_field(
                        name="You can:",
                        value="• Ask questions and contribute to the shared conversation\n• See everyone's questions and the bot's answers\n• Use `/start_session` for your own private thread",
                        inline=False
                    )
                    await message.channel.send(embed=embed, delete_after=15)

            # Update last activity for this user's session and reset reminders
            db.sessions_collection.update_one(
                {"anonymous_user_id": anonymous_user_id, "active": True},
                {"$set": {
                    "last_activity": datetime.datetime.utcnow(),
                    "dm_warning_sent": False,
                    "thread_reminder_sent": False,
                    "second_reminder_sent": False
                }}
            )

            # Show thinking indicator
            user_display_name = self.get_user_display_name(message.author, message.guild)
            thinking_message = None

            try:
                thinking_message = await message.channel.send(f"🤔 Schrödy is thinking... (responding to {user_display_name})")
            except discord.HTTPException:
                pass

            # Cleanup cache periodically
            self._cache_cleanup_counter += 1
            if self._cache_cleanup_counter > 50:
                self._cache_cleanup_counter = 0
                cutoff_time = current_time - 900  # 15 minutes retention
                old_cache = self._message_processing_cache.copy()
                self._message_processing_cache = {
                    key: timestamp for key, timestamp in old_cache.items()
                    if timestamp > cutoff_time
                }

            try:
                # Get or create session
                session = session_manager.get_session(message.channel.id)
                if not session:
                    session = session_manager.create_session(message.channel)

                # Prepare context using session manager
                context_data = session.prepare_context_for_message(message)
                if not context_data:
                    return

                # AI PROCESSING
                try:
                    tutor = self.get_or_create_tutor(str(message.channel.id))
                    response = tutor.ask(context_data['contextual_message'])

                    if not response or not response.strip():
                        return

                except Exception as e:
                    print(f"Error getting AI response: {e}")
                    try:
                        await message.channel.send(f"❌ {message.author.mention}, I encountered an error processing your message. The API servers seem busy at the moment. Please try again after some time.")
                    except discord.HTTPException:
                        pass
                    return

                # Delete thinking message before sending response
                if thinking_message:
                    try:
                        await thinking_message.delete()
                        thinking_message = None
                    except (discord.NotFound, discord.HTTPException):
                        pass

                # Send the response
                response_message = await message.channel.send(f"{message.author.mention}, {response}")

                # Record the conversation in session history
                session.record_conversation(context_data['user_session'], message.content, response)

                # Save to JSON file using LearnLM tutor
                try:
                    json_save_success = tutor.save_session({
                        'user_id': str(message.author.id),
                        'username': message.author.display_name,
                        'thread_id': str(message.channel.id),
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    })
                    if not json_save_success:
                        print(f"Warning: JSON session save failed for thread {message.channel.id}")
                except Exception as json_error:
                    print(f"Warning: JSON session save error for thread {message.channel.id}: {json_error}")

            except Exception as e:
                print(f"Error in message processing: {e}")
                if thinking_message:
                    try:
                        await thinking_message.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass

        except Exception as e:
            print(f"Error in on_message: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Set bot user ID when bot is ready."""
        if self.bot.user:
            session_manager.set_bot_user_id(self.bot.user.id)

    @tasks.loop(minutes=5)
    async def check_inactive_sessions(self):
        """Check for inactive sessions and send reminders/close as needed."""
        try:
            # Clean up inactive sessions across all session managers
            session_manager.cleanup_inactive_sessions()

            # Database cleanup logic - updated for privacy-compliant structure
            now = datetime.datetime.utcnow()
            for session in db.sessions_collection.find({"active": True}):
                try:
                    time_since_activity = now - session.get("last_activity", session["start_time"])
                    anonymous_user_id = session.get("anonymous_user_id")
                    session_id = session.get("session_anonymous_id", "unknown")

                    if not anonymous_user_id:
                        print(f"Error processing session {session_id}: missing anonymous_user_id")
                        continue

                    # 30 minutes - close session
                    if time_since_activity >= datetime.timedelta(minutes=30):
                        db.end_session_by_anonymous_id(anonymous_user_id)
                        # Note: Cannot send DM with anonymous ID for privacy
                        print(f"Session {session_id} ended due to inactivity (30 minutes)")
                        
                    # 15 minutes - second reminder
                        
                    elif time_since_activity >= datetime.timedelta(minutes=15) and not session.get("second_reminder_sent", False):
                        thread_id = session.get("thread_id")
                        tutoring_session = session_manager.get_session(int(thread_id)) if thread_id else None
                        if tutoring_session:
                            try:
                                embed = discord.Embed(
                                    title="⚠️ Session Closing Soon",
                                    description="You've been inactive for 15 minutes.",
                                    color=discord.Color.orange()
                                )
                                embed.add_field(
                                    name="⏰ Session will close in:",
                                    value="15 minutes if no activity is detected",
                                    inline=False
                                )
                                embed.add_field(
                                    name="💬 To continue:",
                                    value="Just send any message or question to keep your session active!",
                                    inline=False
                                )
                                await tutoring_session.thread.send(embed=embed)
                            except (discord.NotFound, discord.HTTPException):
                                pass
                        db.sessions_collection.update_one(
                            {"anonymous_user_id": anonymous_user_id, "active": True},
                            {"$set": {"second_reminder_sent": True}}
                        )

                    # 5 minutes - send thread reminder (only if not already sent)
                    elif time_since_activity >= datetime.timedelta(minutes=5) and not session.get("thread_reminder_sent", False):
                        thread_id = session.get("thread_id")
                        tutoring_session = session_manager.get_session(int(thread_id)) if thread_id else None
                        if tutoring_session:
                            try:
                                embed = discord.Embed(
                                    title="💤 Are you still there?",
                                    description="You've been inactive for 5 minutes.",
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
                            except Exception as e:
                                print(f"Error sending inactivity reminder to thread: {e}")
                        db.sessions_collection.update_one(
                            {"anonymous_user_id": anonymous_user_id, "active": True},
                            {"$set": {"thread_reminder_sent": True}}
                        )

                except Exception as e:
                    print(f"Error processing session for user {session.get('anonymous_user_id', 'unknown')}: {e}")
                    continue

        except Exception as e:
            print(f"Error in check_inactive_sessions: {e}")

    @check_inactive_sessions.before_loop
    async def before_check_inactive_sessions(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()

    async def cog_load(self):
        """Called when the cog is loaded."""
        if self.bot.user:
            session_manager.set_bot_user_id(self.bot.user.id)

    async def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.check_inactive_sessions.cancel()
        self.guest_participation_asked.clear()
        self._message_processing_cache.clear()
        # Clean up tutor instances
        self._tutor_instances.clear()

async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(Tutor(bot))