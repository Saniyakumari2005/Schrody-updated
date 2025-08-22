import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Gemini API configuration 
GEMINI API KEY = os.getenv("GEMINI_API_KEY")
GEMINI MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Rate Limiting and API Management 