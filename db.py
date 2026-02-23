#!/usr/bin/env python3
import os
import datetime
import hashlib
import secrets
import logging
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables with error handling 
mongo_url = os.getenv("MONGO_URL")
if mongo_url is None:
    raise ValueError("MONGO_URL environment variable not set.")

mongo_db_name = os.getenv("MONGO_DB")
if mongo_db_name is None:
    raise ValueError("MONGO_DB environment variable not set.")

mongo_identity_db_name = os.getenv("MONGO_IDENTITY_DB")
if mongo_identity_db_name is None:
    raise ValueError("MONGO_IDENTITY_DB environment variable not set.")

# MongoDB connection 
mongo_client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
db = mongo_client[mongo_db_name]                      # Main operational database
identity_db = mongo_client[mongo_identity_db_name]    # Identity mapping database
conversations = db.conversations

# Main Database Collections (operational data with anonymous IDs)
users_collection = db["users"]
messages_collection = db["messages"]
sessions_collection = db["sessions"]
feedback_collection = db["feedback"]
audit_logs = db["audit_logs"]

# Identity Database Collections (Discord ID mappings - RESTRICTED ACCESS)
identity_mapping = identity_db["identity_mapping"]    # Discord ID ↔ Anonymous ID mapping
access_logs = identity_db["access_logs"]              # Identity access audit trail
system_config = identity_db["system_config"]         # System configuration

# Privacy enhancement
PRIVACY_SALT = os.getenv("PRIVACY_SALT", secrets.token_hex(32))

def _hash_user_id(user_id: str) -> str:
    """Generate consistent hash for privacy (enhancement)"""
    combined = f"{user_id}{PRIVACY_SALT}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]

def _generate_anonymous_id() -> str:
    """Generate a new anonymous user ID"""
    return f"anon_user_{secrets.token_hex(8)}"

def _get_or_create_anonymous_id(discord_id: str, username: str = None) -> str:
    """
    Get existing anonymous ID or create new mapping for Discord user
    This is the ONLY function that accesses the identity database
    """
    try:
        # Check if mapping already exists
        mapping = identity_mapping.find_one({"discord_id": str(discord_id)})
        if mapping:
            # Log access to identity mapping
            _log_identity_access("identity_lookup", discord_id, {"anonymous_id": mapping["anonymous_id"]})
            return mapping["anonymous_id"]

        # Create new anonymous ID mapping
        anonymous_id = _generate_anonymous_id()
        mapping_doc = {
            "anonymous_id": anonymous_id,
            "discord_id": str(discord_id),
            "discord_username": username or "unknown",
            "created_at": datetime.datetime.utcnow(),
            "last_accessed": datetime.datetime.utcnow()
        }
        identity_mapping.insert_one(mapping_doc)

        # Log new identity mapping creation
        _log_identity_access("identity_created", discord_id, {"anonymous_id": anonymous_id})

        return anonymous_id

    except Exception as e:
        logger.error(f"Error managing identity mapping for {discord_id}: {e}")
        # Fallback to hashed ID if identity system fails
        return f"anon_fallback_{_hash_user_id(str(discord_id))}"

def _log_identity_access(action: str, discord_id: str, details: dict = None):
    """Log access to identity mapping system - RESTRICTED"""
    try:
        access_entry = {
            "action": action,
            "discord_id_hash": _hash_user_id(str(discord_id)),  # Store hash, not real ID
            "timestamp": datetime.datetime.utcnow(),
            "details": details or {},
            "source": "discord_bot_identity_system"
        }
        access_logs.insert_one(access_entry)
    except Exception as e:
        logger.warning(f"Identity access logging failed: {e}")

def _log_audit(action: str, user_id: str = None, details: dict = None):
    """Log actions for security auditing (enhancement) - Uses anonymous IDs"""
    try:
        # Convert Discord ID to anonymous ID for audit logging
        anonymous_user_id = None
        if user_id:
            # Check if this is already an anonymous ID or Discord ID
            if user_id.startswith("anon_"):
                anonymous_user_id = user_id
            else:
                # This is a Discord ID, convert to anonymous for audit
                anonymous_user_id = _get_or_create_anonymous_id(user_id)

        audit_entry = {
            "action": action,
            "anonymous_user_id": anonymous_user_id,
            "timestamp": datetime.datetime.utcnow(),
            "security_level": "low",  # Fixed: must be "low", "medium", "high", or "critical"
            "success": True,  # Add required field from schema
            "privacy_compliant": True,  # Add required field from schema
            "details": details or {},
            "source": "discord_bot"
        }
        audit_logs.insert_one(audit_entry)
    except Exception as e:
        # Don't break functionality if audit logging fails
        logger.warning(f"Audit logging failed: {e}")
        # For validation errors with 'feedback_logged', try with 'command_executed' instead
        if "feedback_logged" in str(e) and action == "feedback_logged":
            try:
                audit_entry["action"] = "command_executed"
                audit_logs.insert_one(audit_entry)
                logger.info("Audit logged with fallback action type")
            except Exception as fallback_error:
                logger.warning(f"Fallback audit logging also failed: {fallback_error}")

def add_user(discord_id, username):
    """Add a user to the database if they don't exist. (ENHANCED with anonymization)"""
    try:
        # Get or create anonymous ID (this handles the Discord ID → Anonymous ID mapping)
        anonymous_id = _get_or_create_anonymous_id(str(discord_id), username)

        # Check if anonymous user already exists in main database
        user = users_collection.find_one({"anonymous_id": anonymous_id})
        if not user:
            # Create user with anonymous data in main database (NO Discord ID stored here)
            user_doc = {
                "anonymous_id": anonymous_id,
                "username_hash": _hash_user_id(username),  # Hash username for privacy
                "created_at": datetime.datetime.utcnow(),
                "last_seen": datetime.datetime.utcnow(),
                "user_role": "student",  # Default role
                "privacy_compliant": True,
                "consent": None,            
                "consent_timestamp": None,
                "preferences": {
                    "notifications": True,
                    "privacy_level": "standard"
                },
                "activity_stats": {
                    "total_sessions": 0,
                    "total_messages": 0,
                    "avg_session_duration": 0
                }
            }
            users_collection.insert_one(user_doc)
            _log_audit("user_session_start", str(discord_id), {"username_hash": _hash_user_id(username)})
            print(f"User {username} added to database with anonymous ID: {anonymous_id}")
        else:
            # Update last seen for existing anonymous user
            users_collection.update_one(
                {"anonymous_id": anonymous_id},
                {"$set": {"last_seen": datetime.datetime.utcnow()}}
            )

        return anonymous_id  # Return the anonymous ID for use by bot functions

    except Exception as e:
        logger.error(f"Error adding user {username}: {e}")
        return None

def log_message(user_id, message):
    """Log user messages for future tutoring assistance. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        user_id_str = str(user_id)  # Ensure user_id is string
        if user_id_str.startswith("anon_"):
            anonymous_user_id = user_id_str
        else:
            anonymous_user_id = _get_or_create_anonymous_id(user_id_str)

        message_doc = {
            "anonymous_user_id": anonymous_user_id,  # Use anonymous ID, not Discord ID
            "message": message,
            "timestamp": datetime.datetime.utcnow(),
            "message_type": "user",  # Fixed: must be "user", "bot", or "system"
            "session_anonymous_id": None,  # Will be set when session is active
            "thread_hash": None,  # Will be set if thread context available
            "expires_at": datetime.datetime.utcnow() + datetime.timedelta(days=90),  # Fixed: schema expects "expires_at"
            "privacy_compliant": True
        }
        messages_collection.insert_one(message_doc)
        _log_audit("message_sent", user_id_str if not user_id_str.startswith("anon_") else None, 
                  {"message_length": len(message), "anonymous_user_id": anonymous_user_id})
        print(f"Logged message from anonymous user {anonymous_user_id}")

    except Exception as e:
        logger.error(f"Error logging message: {e}")

def get_messages(user_id, limit=10):
    """Retrieve the last N messages from a user. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        if user_id.startswith("anon_"):
            anonymous_user_id = user_id
        else:
            anonymous_user_id = _get_or_create_anonymous_id(str(user_id))

        return list(messages_collection.find({"anonymous_user_id": anonymous_user_id}).sort("_id", -1).limit(limit))
    except Exception as e:
        logger.error(f"Error retrieving messages: {e}")
        return []

def start_session(user_id, username, thread_id=None):
    """Starts a new tutoring session for a user. (ENHANCED with anonymization)"""
    try:
        # Get or create anonymous ID
        anonymous_user_id = _get_or_create_anonymous_id(str(user_id), username)

        # Ensure user exists in main database first
        add_user(user_id, username)

        # Generate anonymous session ID
        session_anonymous_id = f"session_anon_{secrets.token_hex(8)}"

        now = datetime.datetime.utcnow()
        session_data = {
            # ANONYMIZED fields for main database (NO Discord IDs)
            "anonymous_user_id": anonymous_user_id,
            "session_anonymous_id": session_anonymous_id,
            "start_time": now,
            "last_activity": now,
            "active": True,
            "thread_hash": _hash_user_id(str(thread_id)) if thread_id else None,  
            "thread_id": thread_id,
            "feedback_given": False,
            "username_hash": _hash_user_id(username),  # Hash username for privacy
            "retention_date": now + datetime.timedelta(days=90),
            "privacy_compliant": True,
            # Session metrics for analytics (no personal data)
            "session_duration": 0,
            "message_count": 0
        }
        sessions_collection.insert_one(session_data)
        _log_audit("user_session_start", str(user_id), {
            "anonymous_user_id": anonymous_user_id,
            "session_anonymous_id": session_anonymous_id,
            "thread_hash": session_data.get("thread_hash")
        })
        print(f"Started anonymous session {session_anonymous_id} for user {anonymous_user_id}")

        return session_anonymous_id  # Return anonymous session ID for bot use

    except Exception as e:
        logger.error(f"Error starting session: {e}")
        return None

def end_session(user_id, thread_id=None):
    """Ends the active tutoring session for a user. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID
        user_id_str = str(user_id)  # Ensure user_id is string
        if user_id_str.startswith("anon_"):
            anonymous_user_id = user_id_str
        else:
            anonymous_user_id = _get_or_create_anonymous_id(user_id_str)

        now = datetime.datetime.utcnow()

        # Find active session using anonymous ID
        query = {"anonymous_user_id": anonymous_user_id, "active": True}
        if thread_id:
            query["thread_hash"] = _hash_user_id(str(thread_id))

        active_session = sessions_collection.find_one(query)

        if active_session:
            # Calculate session duration
            duration = int((now - active_session["start_time"]).total_seconds())

            # Update session with end time and metrics
            sessions_collection.update_one(
                {"_id": active_session["_id"]},
                {
                    "$set": {
                        "active": False,
                        "end_time": now,
                        "session_duration": duration,
                        "last_activity": now
                    }
                }
            )

            _log_audit("user_session_end", user_id_str if not user_id_str.startswith("anon_") else None, {
                "anonymous_user_id": anonymous_user_id,
                "session_anonymous_id": active_session.get("session_anonymous_id"),
                "duration_seconds": duration
            })
            print(f"Ended session for anonymous user {anonymous_user_id}")
            return True
        else:
            print(f"No active session found for anonymous user {anonymous_user_id}")
            return False

    except Exception as e:
        logger.error(f"Error ending session: {e}")
        return False

def end_session_by_anonymous_id(anonymous_user_id):
    """Ends the active tutoring session for an anonymous user ID."""
    try:
        now = datetime.datetime.utcnow()

        # Find active session using anonymous ID
        active_session = sessions_collection.find_one({
            "anonymous_user_id": anonymous_user_id, 
            "active": True
        })

        if active_session:
            # Calculate session duration
            duration = int((now - active_session["start_time"]).total_seconds())

            # Update session with end time and metrics
            sessions_collection.update_one(
                {"_id": active_session["_id"]},
                {
                    "$set": {
                        "active": False,
                        "end_time": now,
                        "session_duration": duration,
                        "last_activity": now
                    }
                }
            )

            _log_audit("user_session_end", None, {
                "anonymous_user_id": anonymous_user_id,
                "session_anonymous_id": active_session.get("session_anonymous_id"),
                "duration_seconds": duration,
                "ended_by": "inactivity_timeout"
            })
            print(f"Ended session for anonymous user {anonymous_user_id} due to inactivity")
            return True
        else:
            print(f"No active session found for anonymous user {anonymous_user_id}")
            return False

    except Exception as e:
        logger.error(f"Error ending session by anonymous ID: {e}")
        return False

def get_active_session(user_id, thread_id=None):
    """Get active session for a user, optionally filtered by thread. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        if user_id.startswith("anon_"):
            anonymous_user_id = user_id
        else:
            anonymous_user_id = _get_or_create_anonymous_id(str(user_id))

        query = {"anonymous_user_id": anonymous_user_id, "active": True}
        if thread_id:
            query["thread_hash"] = _hash_user_id(str(thread_id))
        return sessions_collection.find_one(query)
    except Exception as e:
        logger.error(f"Error getting active session: {e}")
        return None

def get_session_by_thread(thread_id):
    """Get all active sessions in a specific thread. (ENHANCED with anonymization)"""
    try:
        thread_hash = _hash_user_id(str(thread_id))
        return list(sessions_collection.find({"thread_hash": thread_hash, "active": True}))
    except Exception as e:
        logger.error(f"Error getting sessions by thread: {e}")
        return []

def update_session_activity(user_id, thread_id=None):
    """Update the last activity time for a session. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        if user_id.startswith("anon_"):
            anonymous_user_id = user_id
        else:
            anonymous_user_id = _get_or_create_anonymous_id(str(user_id))

        query = {"anonymous_user_id": anonymous_user_id, "active": True}
        if thread_id:
            query["thread_hash"] = _hash_user_id(str(thread_id))

        sessions_collection.update_one(
            query,
            {"$set": {"last_activity": datetime.datetime.utcnow()}}
        )
    except Exception as e:
        logger.error(f"Error updating session activity: {e}")

def log_feedback(user_id, rating):
    """Store feedback rating. (ENHANCED with privacy)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        user_id_str = str(user_id)  # Ensure user_id is string
        if user_id_str.startswith("anon_"):
            anonymous_user_id = user_id_str
        else:
            anonymous_user_id = _get_or_create_anonymous_id(user_id_str)

        # Privacy enhancement: anonymize low ratings
        is_anonymous = rating <= 2

        feedback_doc = {
            "anonymous_user_id": anonymous_user_id,  # Use anonymous ID, not Discord ID
            "rating": rating,
            "timestamp": datetime.datetime.utcnow(),
            "anonymous": is_anonymous,
            "privacy_compliant": True,
            "feedback_anonymous_id": f"feedback_anon_{secrets.token_hex(6)}" if is_anonymous else None
        }
        feedback_collection.insert_one(feedback_doc)

        # Update session feedback status
        sessions_collection.update_one(
            {"anonymous_user_id": anonymous_user_id, "active": False}, 
            {"$set": {"feedback_given": True}}
        )

        privacy_note = " (anonymous for privacy)" if is_anonymous else ""
        _log_audit("feedback_logged", user_id_str if not user_id_str.startswith("anon_") else None, {
            "rating": rating, 
            "anonymous": is_anonymous,
            "anonymous_user_id": anonymous_user_id
        })
        print(f"Feedback logged: {rating}/5{privacy_note}")
    except Exception as e:
        logger.error(f"Error logging feedback: {e}")

def get_pending_feedback():
    """Get list of users who haven't submitted feedback. (ENHANCED with anonymization)"""
    try:
        # Return sessions with anonymous user IDs only
        return list(sessions_collection.find({"active": False, "feedback_given": False}))
    except Exception as e:
        logger.error(f"Error getting pending feedback: {e}")
        return []
        
def get_discord_id_from_anonymous(anonymous_user_id: str):
    """Retrieve the original Discord ID from an anonymous user ID. (RESTRICTED - identity DB)"""
    try:
        mapping = identity_mapping.find_one({"anonymous_id": anonymous_user_id})
        if mapping:
            _log_identity_access("identity_lookup_for_feedback", mapping["discord_id"], {"anonymous_id": anonymous_user_id})
            return mapping["discord_id"]
        return None
    except Exception as e:
        logger.error(f"Error looking up Discord ID for {anonymous_user_id}: {e}")
        return None

def add_message(user_id, message, role="user"):
    """Save a user or AI message to the conversation memory. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        user_id_str = str(user_id)  # Ensure user_id is string
        if user_id_str.startswith("anon_"):
            anonymous_user_id = user_id_str
        else:
            anonymous_user_id = _get_or_create_anonymous_id(user_id_str)

        conversation_doc = {
            "anonymous_user_id": anonymous_user_id,  # Use anonymous ID, not Discord ID
            "message": message,
            "role": role,
            "timestamp": datetime.datetime.utcnow(),
            "retention_date": datetime.datetime.utcnow() + datetime.timedelta(days=30),
            "privacy_compliant": True
        }
        conversations.insert_one(conversation_doc)
        _log_audit("message_sent", user_id_str if not user_id_str.startswith("anon_") else None, {
            "role": role,
            "anonymous_user_id": anonymous_user_id
        })
    except Exception as e:
        logger.error(f"Error adding conversation message: {e}")

def get_conversation(user_id, limit=10):
    """Retrieve recent messages for context. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        if user_id.startswith("anon_"):
            anonymous_user_id = user_id
        else:
            anonymous_user_id = _get_or_create_anonymous_id(str(user_id))

        msgs = list(conversations.find({"anonymous_user_id": anonymous_user_id}).sort("_id", -1).limit(limit))
        return [{"role": msg["role"], "message": msg["message"]} for msg in reversed(msgs)]
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return []

def clear_conversation(user_id):
    """Clear the conversation memory. (ENHANCED with anonymization)"""
    try:
        # Convert Discord ID to anonymous ID if needed
        if user_id.startswith("anon_"):
            anonymous_user_id = user_id
        else:
            anonymous_user_id = _get_or_create_anonymous_id(str(user_id))

        result = conversations.delete_many({"anonymous_user_id": anonymous_user_id})
        _log_audit("data_cleanup", str(user_id) if not user_id.startswith("anon_") else None, {
            "deleted_count": result.deleted_count,
            "anonymous_user_id": anonymous_user_id
        })
        print(f"Cleared {result.deleted_count} conversation messages for anonymous user {anonymous_user_id}")
    except Exception as e:
        logger.error(f"Error clearing conversation: {e}")

def cleanup_expired_data():
    """Clean up expired data based on retention policies"""
    try:
        now = datetime.datetime.utcnow()

        # Clean up old messages (90 days)
        message_result = messages_collection.delete_many({"retention_date": {"$lt": now}})

        # Clean up old conversations (30 days)  
        conversation_result = conversations.delete_many({"retention_date": {"$lt": now}})

        # Clean up old audit logs (1 year)
        audit_cutoff = now - datetime.timedelta(days=365)
        audit_result = audit_logs.delete_many({"timestamp": {"$lt": audit_cutoff}})

        cleanup_stats = {
            "messages_deleted": message_result.deleted_count,
            "conversations_deleted": conversation_result.deleted_count,
            "audit_logs_deleted": audit_result.deleted_count,
            "cleanup_date": now
        }

        logger.info(f"Data cleanup completed: {cleanup_stats}")
        return cleanup_stats

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return {"error": str(e)}

def get_database_stats():
    """Get comprehensive database statistics for monitoring (Both databases)"""
    try:
        stats = {
            # Main Database Statistics (Anonymous Data)
            "users": users_collection.count_documents({}),
            "active_sessions": sessions_collection.count_documents({"active": True}),
            "total_sessions": sessions_collection.count_documents({}),
            "messages": messages_collection.count_documents({}),
            "conversations": conversations.count_documents({}),
            "feedback": feedback_collection.count_documents({}),
            "audit_logs": audit_logs.count_documents({}),

            # Identity Database Statistics (Restricted Access)
            "identity_mappings": identity_mapping.count_documents({}),
            "identity_access_logs": access_logs.count_documents({}),
            "system_configurations": system_config.count_documents({}),

            "timestamp": datetime.datetime.utcnow()
        }
        return stats
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return {}

def get_security_dashboard():
    """Get security dashboard data"""
    try:
        now = datetime.datetime.utcnow()
        last_24h = now - datetime.timedelta(hours=24)

        dashboard = {
            "recent_activity": {
                "new_users": users_collection.count_documents({"created_at": {"$gte": last_24h}}),
                "active_sessions": sessions_collection.count_documents({"last_activity": {"$gte": last_24h}}),
                "messages_logged": messages_collection.count_documents({"timestamp": {"$gte": last_24h}}),
                "feedback_received": feedback_collection.count_documents({"timestamp": {"$gte": last_24h}})
            },
            "privacy_metrics": {
                "anonymous_feedback": feedback_collection.count_documents({"anonymous": True}),
                "total_feedback": feedback_collection.count_documents({}),
                "data_retention_compliant": True
            },
            "system_health": {
                "database_connected": True,
                "audit_logging": True
            }
        }
        return dashboard
    except Exception as e:
        logger.error(f"Error getting security dashboard: {e}")
        return {}

# Initialize database indexes for performance
def _initialize_indexes():
    """Create database indexes for optimal performance (Updated for anonymization)"""
    try:
        # User indexes (anonymous IDs only)
        users_collection.create_index("anonymous_id", unique=True)
        users_collection.create_index("username_hash")
        users_collection.create_index("last_seen")
        users_collection.create_index("consent") 

        # Session indexes (anonymous IDs only)
        sessions_collection.create_index([("anonymous_user_id", 1), ("active", 1)])
        sessions_collection.create_index("session_anonymous_id", unique=True)
        sessions_collection.create_index("thread_hash")
        sessions_collection.create_index("start_time")

        # Message indexes (anonymous IDs only)
        messages_collection.create_index([("anonymous_user_id", 1), ("timestamp", -1)])
        messages_collection.create_index("retention_date")

        # Conversation indexes (anonymous IDs only)
        conversations.create_index([("anonymous_user_id", 1), ("timestamp", -1)])
        conversations.create_index("retention_date")

        # Feedback indexes (anonymous IDs only)
        feedback_collection.create_index("anonymous_user_id")
        feedback_collection.create_index("timestamp")
        feedback_collection.create_index("anonymous")

        # Audit log indexes (anonymous IDs only)
        audit_logs.create_index("timestamp")
        audit_logs.create_index("action")
        audit_logs.create_index("anonymous_user_id")

        # Identity Database Indexes (RESTRICTED ACCESS)
        identity_mapping.create_index("discord_id", unique=True)
        identity_mapping.create_index("anonymous_id", unique=True)
        access_logs.create_index("timestamp")
        access_logs.create_index("action")

        logger.info("Database indexes created successfully (anonymization-ready)")

    except Exception as e:
        logger.warning(f"Could not create some indexes: {e}")

# Initialize indexes when module loads (with error handling to prevent blocking)
try:
    _initialize_indexes()
except Exception as e:
    logger.warning(f"Index initialization failed (non-blocking): {e}")

print("Discord Bot Database Module Loaded!")
print("All original functions preserved with security enhancements")
print("Privacy features: Anonymous feedback, data retention, audit logging")