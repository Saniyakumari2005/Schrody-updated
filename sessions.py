
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

        try:
            anonymous_user_id = db._get_or_create_anonymous_id(str(self.user.id), self.user.name)
            db.add_message(anonymous_user_id, message_content, "user")
            db.add_message(anonymous_user_id, response, "assistant")
            db.log_message(anonymous_user_id, message_content)
            db.log_message(anonymous_user_id, response)

            result = db.sessions_collection.update_one(
                {"anonymous_user_id": anonymous_user_id, "active": True},
                {"$inc": {"message_count": 1}}
            )
            if result.matched_count == 0:
                print(f"Note: No active DB session for {anonymous_user_id} (guest participant)")
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
        self.shared_history = db.load_shared_history(str(thread.id))

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
        """Prepare shared conversation context for AI processing."""
        if not self.active:
            return None

        self.remove_inactive_users()

        user_session = self.add_user(message.author)

        if not user_session.active:
            return None

        recent = self.shared_history[-10:]
        context_lines = []
        for entry in recent:
            context_lines.append(f"{entry['username']}: {entry['user_message']}")
            context_lines.append(f"Assistant: {entry['bot_response']}")

        contextual_message = ""
        active_users = self.get_active_users()
        if len(active_users) > 1:
            names = ", ".join(u.display_name for u in active_users)
            contextual_message += f"[This is a multiuser session with: {names}]\n\n"

        if context_lines:
            contextual_message += "Previous conversation:\n" + "\n".join(context_lines) + "\n\n"

        contextual_message += f"{message.author.display_name}: {message.content}"

        return {
            'contextual_message': contextual_message,
            'user_session': user_session
        }

    def record_conversation(self, user_session, user_message, bot_response):
        """Record conversation in both shared history and the individual user's history."""
        # Shared thread log
        self.shared_history.append({
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'user_id': str(user_session.user.id),
            'username': user_session.user.display_name,
            'user_message': user_message,
            'bot_response': bot_response
        })
        if len(self.shared_history) > 50:
            self.shared_history = self.shared_history[-50:]
            
        db.save_shared_history(str(self.thread.id), self.shared_history)

        # Individual user history (still useful for per-user stats)
        user_session.add_to_history(user_message, bot_response)

    async def end_user_session(self, user):
        """End a specific user's session."""
        if user.id in self.user_sessions:
            user_session = self.user_sessions[user.id]
            user_session.active = False
            anonymous_user_id = db._get_or_create_anonymous_id(str(user.id), user.name)
            db.end_session_by_anonymous_id(anonymous_user_id)
            del self.user_sessions[user.id]
            

    async def end_session(self):
        """End the entire tutoring session."""
        async with self._session_lock:
            self.active = False

            # End all user sessions
            for user_id, user_session in self.user_sessions.items():
                user_session.active = False
                anonymous_user_id = db._get_or_create_anonymous_id(str(user_session.user.id), user_session.user.name)
                db.end_session_by_anonymous_id(anonymous_user_id)

            user_mentions = [f"<@{user_id}>" for user_id in self.user_sessions.keys()]
            if user_mentions:
                await self.thread.send(f"✅ {', '.join(user_mentions)}, the tutoring session has ended. Please provide feedback with `/feedback <1-5>`.")

            self.user_sessions.clear()
            self.shared_history.clear()
            try:
                db.shared_history_collection.delete_one({"thread_id": str(self.thread.id)})
            except Exception as e:
                print(f"Warning: Could not clear shared history for thread {self.thread.id}: {e}")

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

