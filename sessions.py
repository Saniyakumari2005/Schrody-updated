
import datetime
import learnlm
import db
import discord
from typing import Dict, Optional, Set
import asyncio
import hashlib

class UserSession:
    """Represents an individual user's session within a tutoring thread."""

    def __init__(self, user, thread):
        self.user = user
        self.thread = thread
        self.start_time = datetime.datetime.utcnow()
        self.active = True
        self.conversation_history = []
        self.last_activity = datetime.datetime.utcnow()
        self._response_count = 0

    def add_to_history(self, message_content: str, response: str):
        """Add message and response to user's conversation history."""
        self.conversation_history.append({
            'timestamp': datetime.datetime.utcnow(),
            'user_message': message_content,
            'bot_response': response
        })
        self.last_activity = datetime.datetime.utcnow()
        self._response_count += 1

        # IMPORTANT: Persist to database for data retention and analytics
        import db
        try:
            # Log to conversations collection (for conversational context)
            db.add_message(self.user.id, message_content, "user")
            db.add_message(self.user.id, response, "assistant")

            # Log to messages collection (for discrete message analytics)
            db.log_message(self.user.id, message_content)
            db.log_message(self.user.id, response)

            # Update session message count
            anonymous_user_id = db._get_or_create_anonymous_id(str(self.user.id))
            db.sessions_collection.update_one(
                {"anonymous_user_id": anonymous_user_id, "active": True},
                {"$inc": {"message_count": 1}}
            )
        except Exception as e:
            print(f"Warning: Failed to persist conversation to database: {e}")

    def get_context(self) -> str:
        """Get conversation context for this specific user."""
        if not self.conversation_history:
            return ""

        recent_history = self.conversation_history[-5:]
        context = []
        for entry in recent_history:
            context.append(f"User: {entry['user_message']}")
            context.append(f"Assistant: {entry['bot_response']}")

        return "\n".join(context)

class TutoringSession:
    """Represents a tutoring session that can handle multiple users in the same thread."""

    def __init__(self, thread):
        self.thread = thread
        self.start_time = datetime.datetime.utcnow()
        self.active = True
        self.user_sessions: Dict[int, UserSession] = {}
        self.session_timeout = 1800
        self._session_lock = asyncio.Lock()

    def add_user(self, user) -> UserSession:
        """Add a new user to the session or return existing user session."""
        if user.id not in self.user_sessions:
            self.user_sessions[user.id] = UserSession(user, self.thread)
        return self.user_sessions[user.id]

    def get_user_session(self, user_id: int) -> Optional[UserSession]:
        """Get user session by user ID."""
        return self.user_sessions.get(user_id)

    def remove_inactive_users(self):
        """Remove users who have been inactive for too long."""
        try:
            current_time = datetime.datetime.utcnow()
            inactive_users = []

            for user_id, user_session in self.user_sessions.items():
                try:
                    if hasattr(user_session, 'last_activity') and user_session.last_activity:
                        time_since_activity = (current_time - user_session.last_activity).total_seconds()
                        if time_since_activity > self.session_timeout:
                            inactive_users.append(user_id)
                    else:
                        inactive_users.append(user_id)
                except (AttributeError, TypeError, ValueError) as e:
                    print(f"Error calculating activity time for user {user_id}: {e}")
                    inactive_users.append(user_id)

            for user_id in inactive_users:
                if user_id in self.user_sessions:
                    del self.user_sessions[user_id]

        except Exception as e:
            print(f"Error in remove_inactive_users: {e}")



    def prepare_context_for_message(self, message):
        """Prepare conversation context for AI processing (called from tutor.py)."""
        if not self.active:
            return None

        # User session management
        self.remove_inactive_users()
        user_session = self.add_user(message.author)

        if not user_session.active:
            return None

        # Prepare context
        context = user_session.get_context()
        contextual_message = f"User: {message.author.display_name}\n"
        if context:
            contextual_message += f"Previous conversation:\n{context}\n\n"
        contextual_message += f"Current message: {message.content}"

        return {
            'contextual_message': contextual_message,
            'user_session': user_session
        }

    def record_conversation(self, user_session, user_message, bot_response):
        """Record the conversation in user's history (called from tutor.py)."""
        user_session.add_to_history(user_message, bot_response)

    async def end_user_session(self, user):
        """End a specific user's session."""
        if user.id in self.user_sessions:
            user_session = self.user_sessions[user.id]
            user_session.active = False
            db.end_session(user.id, self.thread.id)
            del self.user_sessions[user.id]

    async def end_session(self):
        """End the entire tutoring session."""
        async with self._session_lock:
            self.active = False

            # End all user sessions
            for user_id, user_session in self.user_sessions.items():
                user_session.active = False
                db.end_session(user_id, self.thread.id)

            # Notify users
            user_mentions = [f"<@{user_id}>" for user_id in self.user_sessions.keys()]
            if user_mentions:
                mentions_text = ", ".join(user_mentions)
                await self.thread.send(f"✅ {mentions_text}, the tutoring session has ended. Please provide feedback with `/feedback <1-5>`.")

            self.user_sessions.clear()

    def get_active_users(self) -> list:
        """Get list of active users in the session."""
        return [user_session.user for user_session in self.user_sessions.values() if user_session.active]

    def get_session_stats(self) -> dict:
        """Get statistics about the session."""
        total_responses = sum(us._response_count for us in self.user_sessions.values())
        return {
            'total_users': len(self.user_sessions),
            'active_users': len([us for us in self.user_sessions.values() if us.active]),
            'session_duration': (datetime.datetime.utcnow() - self.start_time).total_seconds(),
            'total_responses': total_responses,
            'users': [us.user.display_name for us in self.user_sessions.values()]
        }

class SessionManager:
    """Manages multiple tutoring sessions across different threads."""

    def __init__(self):
        self.sessions: Dict[int, TutoringSession] = {}
        self.bot_user_id = None

    def set_bot_user_id(self, bot_user_id: int):
        """Set the bot's user ID for message filtering."""
        self.bot_user_id = bot_user_id
        print(f"DEBUG: Bot user ID set to {bot_user_id}")

    def create_session(self, thread) -> TutoringSession:
        """Create a new tutoring session."""
        # Prevent duplicate session creation
        if thread.id in self.sessions:
            return self.sessions[thread.id]

        session = TutoringSession(thread)
        self.sessions[thread.id] = session
        print(f"DEBUG: Created session for thread {thread.id}")
        return session

    def get_session(self, thread_id: int) -> Optional[TutoringSession]:
        """Get existing session by thread ID."""
        return self.sessions.get(thread_id)

    async def end_session(self, thread_id: int):
        """End and remove a session."""
        if thread_id in self.sessions:
            await self.sessions[thread_id].end_session()
            del self.sessions[thread_id]
            print(f"DEBUG: Ended session for thread {thread_id}")

    def cleanup_inactive_sessions(self):
        """Clean up inactive users across all sessions."""
        try:
            for session in list(self.sessions.values()):
                if session.active:
                    session.remove_inactive_users()
        except Exception as e:
            print(f"Error in cleanup_inactive_sessions: {e}")

    def get_all_sessions_stats(self) -> dict:
        """Get statistics for all active sessions."""
        return {
            'total_sessions': len(self.sessions),
            'active_sessions': len([s for s in self.sessions.values() if s.active]),
            'total_users': sum(len(s.user_sessions) for s in self.sessions.values())
        }

# Global session manager instance
session_manager = SessionManager()

# Bot Command Handlers 
async def start_session_command(slash):
    """Start a new tutoring session in the current thread."""
    session = session_manager.create_session(slash.channel)
    await slash.send(f"🎓 Tutoring session started! Users can now ask questions and I'll maintain separate conversations with each person.")

async def join_session_command(slash):
    """Join an existing tutoring session."""
    session = session_manager.get_session(slash.channel.id)
    if session and session.active:
        user_session = session.add_user(slash.author)
        await slash.send(f"✅ {slash.author.mention}, you've joined the tutoring session!")
    else:
        await slash.send("❌ No active tutoring session in this thread. Start one with `/start_session`.")

async def leave_session_command(slash):
    """Leave the current tutoring session."""
    session = session_manager.get_session(slash.channel.id)
    if session:
        await session.end_user_session(slash.author)
    else:
        await slash.send("❌ No active tutoring session in this thread.")

async def session_stats_command(slash):
    """Show statistics about the current session."""
    session = session_manager.get_session(slash.channel.id)
    if session and session.active:
        stats = session.get_session_stats()
        await slash.send(f"📊 Session Stats:\n"
                        f"• Total users: {stats['total_users']}\n"
                        f"• Active users: {stats['active_users']}\n"
                        f"• Total responses: {stats['total_responses']}\n"
                        f"• Duration: {stats['session_duration']:.0f} seconds\n"
                        f"• Users: {', '.join(stats['users'])}")
    else:
        await slash.send("❌ No active tutoring session in this thread.")