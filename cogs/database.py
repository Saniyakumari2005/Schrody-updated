
import discord
from discord import app_commands
from discord.ext import commands
import db
import datetime

class Database(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="db_status", description="Check database connection and show statistics")
    async def db_status(self, interaction: discord.Interaction):
        """Check if database is working and show basic stats."""
        # Check if user has administrator permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command is restricted to administrators only.", ephemeral=True)
            return

        try:
            # Test database connection
            db.mongo_client.admin.command('ping')

            # Get collection counts
            users_count = db.users_collection.count_documents({})
            messages_count = db.messages_collection.count_documents({})
            sessions_count = db.sessions_collection.count_documents({})
            feedback_count = db.feedback_collection.count_documents({})
            conversations_count = db.conversations.count_documents({})

            # Get active sessions
            active_sessions = db.sessions_collection.count_documents({"active": True})

            embed = discord.Embed(
                title="🗄️ Database Status",
                description="Database connection is working properly!",
                color=discord.Color.green()
            )

            embed.add_field(name="📊 Collection Statistics", value=f"""
            **Users:** {users_count}
            **Messages:** {messages_count}
            **Sessions:** {sessions_count}
            **Active Sessions:** {active_sessions}
            **Feedback:** {feedback_count}
            **Conversations:** {conversations_count}
            """, inline=False)

            embed.add_field(name="🔗 Connection Info", value=f"""
            **Database:** {db.mongo_db_name}
            **Status:** ✅ Connected
            **Timestamp:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
            """, inline=False)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Database Error",
                description=f"Failed to connect to database: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed)

    @app_commands.command(name="db_test", description="Test database operations")
    async def db_test(self, interaction: discord.Interaction):
        """Test basic database operations."""
        # Check if user has administrator permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command is restricted to administrators only.", ephemeral=True)
            return

        try:
            user_id = str(interaction.user.id)

            # Test adding a user
            db.add_user(interaction.user.id, interaction.user.name)

            # Test logging a message
            test_message = f"Database test at {datetime.datetime.utcnow()}"
            db.log_message(user_id, test_message)

            # Test retrieving messages
            recent_messages = db.get_messages(user_id, limit=3)

            # Test conversation functions
            db.add_message(user_id, "Test conversation message", role="user")
            conversation = db.get_conversation(user_id, limit=3)

            embed = discord.Embed(
                title="🧪 Database Test Results",
                description="All database operations completed successfully!",
                color=discord.Color.blue()
            )

            embed.add_field(name="✅ Operations Tested", value="""
            • User creation/update
            • Message logging
            • Message retrieval
            • Conversation management
            """, inline=False)

            embed.add_field(name="📝 Recent Messages", value=f"Found {len(recent_messages)} recent messages", inline=True)
            embed.add_field(name="💬 Conversation", value=f"Found {len(conversation)} conversation entries", inline=True)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Database Test Failed",
                description=f"Error during database test: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed)

async def setup(bot):
    await bot.add_cog(Database(bot))