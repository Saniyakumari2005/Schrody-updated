import os
import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get environment variables with error handling
mongo_url = os.getenv("MONGO_URL")
if mongo_url is None:
    raise ValueError("MONGO_URL environment variable not set.")

mongo_db_name = os.getenv("MONGO_DB")
if mongo_db_name is None:
    raise ValueError("MONGO_DB environment variable not set.")

mongo_client = MongoClient(mongo_url)
db = mongo_client[mongo_db_name]
conversations = db.conversations

# Collections
users_collection = db["users"]
messages_collection = db["messages"]
sessions_collection = db["sessions"]
feedback_collection = db["feedback"]

def add_user(discord_id, username):
    """Add a user to the database if they don't exist."""
    user = users_collection.find_one({"discord_id": str(discord_id)})
    if not user:
        users_collection.insert_one({"discord_id": str(discord_id), "username": username})
        print(f"✅ User {username} added to database.")

def log_message(user_id, message):
    """Log user messages for future tutoring assistance."""
    messages_collection.insert_one({
        "user_id": str(user_id),
        "message": message
    })
    print(f"💾 Logged message from user {user_id}")

def get_messages(user_id, limit=10):
    """Retrieve the last N messages from a user."""
    return list(messages_collection.find({"user_id": str(user_id)}).sort("_id", -1).limit(limit))

def start_session(user_id, username, thread_id=None):
    """Starts a new tutoring session for a user."""
    now = datetime.datetime.utcnow()
    session_data = {
        "user_id": str(user_id),
        "username": username,
        "start_time": now,
        "last_activity": now,
        "active": True,
        "thread_reminder_sent": False,
        "dm_warning_sent": False,
        "thread_id": str(thread_id) if thread_id else None,
        "feedback_given": False,
    }
    sessions_collection.insert_one(session_data)
    print(f"✅ Started session for {username} (ID: {user_id}) in thread {thread_id}")

def end_session(user_id, thread_id=None):
    """End a tutoring session."""
    if thread_id:
        sessions_collection.update_one(
            {"user_id": str(user_id), "thread_id": str(thread_id), "active": True}, 
            {"$set": {"active": False, "end_time": datetime.datetime.utcnow()}}
        )
    else:
        sessions_collection.update_one(
            {"user_id": str(user_id), "active": True}, 
            {"$set": {"active": False, "end_time": datetime.datetime.utcnow()}}
        )
def get_active_session(user_id, thread_id=None):
    """Get active session for a user, optionally filtered by thread."""
    query = {"user_id": str(user_id), "active": True}
    if thread_id:
        query["thread_id"] = str(thread_id)
    return sessions_collection.find_one(query)

def get_session_by_thread(thread_id):
    """Get all active sessions in a specific thread."""
    return list(sessions_collection.find({"thread_id": str(thread_id), "active": True}))

def update_session_activity(user_id, thread_id=None):
    """Update the last activity time for a session."""
    query = {"user_id": str(user_id), "active": True}
    if thread_id:
        query["thread_id"] = str(thread_id)

    sessions_collection.update_one(
        query,
        {"$set": {"last_activity": datetime.datetime.utcnow()}}
    )

def log_feedback(user_id, rating):
    """Store feedback rating."""
    feedback_collection.insert_one({
        "user_id": str(user_id),
        "rating": rating,
        "timestamp": datetime.datetime.utcnow()
    })
    sessions_collection.update_one({"user_id": str(user_id)}, {"$set": {"feedback_given": True}})

def get_pending_feedback():
    """Get list of users who haven't submitted feedback."""
    return sessions_collection.find({"active": False, "feedback_given": False})

def add_message(user_id, message, role="user"):
    """Save a user or AI message to the conversation memory."""
    conversations.insert_one({
        "user_id": user_id,
        "message": message,
        "role": role
    })

def get_conversation(user_id, limit=10):
    """Retrieve recent messages for context."""
    msgs = list(conversations.find({"user_id": user_id}).sort("_id", -1).limit(limit))
    return [{"role": msg["role"], "message": msg["message"]} for msg in reversed(msgs)]

def clear_conversation(user_id):
    """Clear the conversation memory."""
    conversations.delete_many({"user_id": user_id})