import os
import json
from datetime import datetime, timedelta
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Optional, List, Dict, Union

# Load API keys
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise Exception("Missing GEMINI_API_KEY. Please add it to your .env file.")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Shared system prompt for the tutor
TUTOR_SYSTEM_PROMPT = """You are **Schrödy**, a dedicated and resourceful research assistant with access to web search. Your goal is to empower users to become better researchers by helping them refine their inquiries, formulate strong search strategies, and locate high-quality resources, rather than simply providing summaries or direct answers.

**Your Persona:**
    
- **Methodical:** You value structure, reliable sources, and clear reasoning.
- **Inquisitive:** You ask clarifying questions to narrow down broad topics into actionable research questions.
- **Resource-Oriented:** You focus on where information lives (journals, databases, reports) and how to retrieve it.
- **Professional yet Approachable:** Maintain a helpful, encouraging, and academic tone. Research can be frustrating; be the supportive partner in the process.

**Your Methodology:**

1. **Clarify the Objective:**
    
    - Begin by assessing the user's current research goal. Is it a broad exploration, specific data retrieval, or fact-checking?
        
    - If the user asks a vague question, help them narrow the scope (e.g., "Are you looking for historical context or current statistical data?").
        
2. **Refine the Question:**
    
    - **Do not answer the question directly.** Instead, help the user formulate a better search query or research thesis.
        
    - Suggest specific **keywords**, **Boolean operators** (AND, OR, NOT), or phrasing that will yield the best results.
        
3. **Source Navigation (Guide, don't tell):**
    
    - Instead of giving the fact, point the user to the type of resource where the answer resides (e.g., "For this statistic, you should look at government census data or World Bank reports. Try searching for...").
        
    - Provide URLs or names of specific reports/journals found via your web search, then encourage the user to extract the specific data points themselves.
        
4. **Evaluate and Verify:**
    
    - Prompt the user to evaluate the credibility of sources. (e.g., "I found this article, but it is an opinion piece. How might that affect your argument?").
        
    - If the user provides an incorrect fact, guide them to a contradictory source and ask them to compare the evidence.
        
5. **Synthesize Findings:**
    
    - Once the user has found information, ask them how it fits into their broader project or argument.
    
6. **The Feedback Loop:**
    
    - **Actively ask the user:** "Would you like specific feedback on your current draft/findings?"
        
    - If the user agrees, provide a structured review containing:
        
        - **Positives:** Highlight strong reasoning, good source selection, or clear articulation.
            
        - **Critiques:** Identify logical gaps, bias, weak evidence, or formatting issues.
            
        - **Improvements:** Offer actionable steps to strengthen the work (e.g., "Try looking for a source that argues the opposite view to strengthen your counter-argument").
        

**Web Search Guidelines:**

- Use search to identify **sources**, **databases**, and **recent publications**, not just to find quick facts to copy-paste. 
- When you find a relevant resource, provide the title, author/organization, and a brief description of why it is useful to the user's specific query.
- **Always cite sources** clearly.
    

**Output Formatting:**

- **Structure:** Use bullet points and lists to suggest keywords, resources, or search strategies. Keep outputs concise and productive.
- **Formatting:** Use Discord-friendly formatting (bold with **text**, italic with _text_, code with `text`)
- **Mathematics:** ALWAYS use Unicode symbols for mathematical expressions since LaTeX is not supported.
    
    - Use × for multiplication (not *)
    - Use ÷ for division (not /)
    - Use ² ³ ⁴ for superscripts 
    - Use ₁ ₂ ₃ for subscripts   
    - Use √ for square root  
    - Use π for pi 
    - Use ∞ for infinity 
    - Use ≤ ≥ ≠ ≈ for comparison operators 
    - Use ∫ for integration  
    - Use Σ for summation  
    - Use ∂ for partial derivatives  
    - Use α β γ δ θ λ μ σ etc. for Greek letters
            
- *No LaTeX*: Never use LaTeX syntax like $x^2$ or \frac{}{} - always use Unicode equivalents
    
Remember and reference previous parts of the conversation when relevant."""

class ContextMode:
    """Enum-like class for context modes."""
    ACTIVE_SESSION = "active_session"
    FULL_HISTORY = "full_history"
    SMART_SUMMARY = "smart_summary"

class SessionManager:
    """Handles session persistence and context management."""

    def __init__(self, storage_dir: str = "sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)

    def save_session(self, session_id: str, conversation_history: List[Dict], metadata: Dict = None):
        """Save session to persistent storage with error handling."""
        try:
            session_data = {
                'conversation_history': conversation_history,
                'metadata': metadata or {},
                'last_updated': datetime.now().isoformat(),
                'total_exchanges': len(conversation_history)
            }

            session_file = self.storage_dir / f"{session_id}.json"
            
            # Create a temporary file first to avoid corruption
            temp_file = session_file.with_suffix('.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            
            # Atomically replace the original file
            temp_file.replace(session_file)
            
            print(f"✅ Session '{session_id}' saved successfully to {session_file}")
            
        except PermissionError as e:
            print(f"❌ Permission denied when saving session '{session_id}': {e}")
            raise
        except OSError as e:
            print(f"❌ OS error when saving session '{session_id}': {e}")
            raise
        except json.JSONEncodeError as e:
            print(f"❌ JSON encoding error when saving session '{session_id}': {e}")
            raise
        except Exception as e:
            print(f"❌ Unexpected error when saving session '{session_id}': {e}")
            raise

    def load_session(self, session_id: str) -> Optional[Dict]:
        """Load session from persistent storage with error handling."""
        session_file = self.storage_dir / f"{session_id}.json"
        
        if not session_file.exists():
            print(f"📁 Session file '{session_id}.json' not found")
            return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
                print(f"✅ Session '{session_id}' loaded successfully")
                return session_data
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error when loading session '{session_id}': {e}")
            print(f"💡 Session file may be corrupted: {session_file}")
            return None
        except PermissionError as e:
            print(f"❌ Permission denied when loading session '{session_id}': {e}")
            return None
        except OSError as e:
            print(f"❌ OS error when loading session '{session_id}': {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error when loading session '{session_id}': {e}")
            return None

    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """Get session metadata without loading full history."""
        session_data = self.load_session(session_id)
        if not session_data:
            return None

        return {
            'session_id': session_id,
            'last_updated': session_data.get('last_updated'),
            'total_exchanges': session_data.get('total_exchanges', 0),
            'metadata': session_data.get('metadata', {})
        }

    def list_sessions(self) -> List[Dict]:
        """List all available sessions with their info."""
        sessions = []
        for session_file in self.storage_dir.glob("*.json"):
            session_id = session_file.stem
            info = self.get_session_info(session_id)
            if info:
                sessions.append(info)

        # Sort by last updated (most recent first)
        sessions.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        return sessions

class LearnLMTutor:
    """Enhanced tutor with sophisticated context management."""

    # Class-level search configuration for web search
    SEARCH_CONFIG = {
        "web_search": {
            "enable_web_search": True
        }
    }

    # Keywords that suggest current information is needed
    SEARCH_KEYWORDS = [
        "current", "recent", "latest", "today", "now", "2024", "2025", 
        "news", "update", "updated", "development", "breakthrough", 
        "trending", "this year", "this month", "recently", "web", "search", "look up"
    ]

    # Context management settings
    DEFAULT_ACTIVE_CONTEXT = 5  # exchanges to keep in active session
    DEFAULT_SUMMARY_CONTEXT = 3  # exchanges for smart summary mode
    MAX_CONTEXT_TOKENS = 4000  # rough token limit for context

    def __init__(self, model_name: str = 'gemini-2.5-flash', session_id: Optional[str] = None, 
                 active_context_limit: int = None, storage_dir: str = "sessions"):
        """
        Initialize the tutor with enhanced context management.

        Args:
            model_name: Gemini model to use
            session_id: Unique session identifier for persistence
            active_context_limit: Number of recent exchanges to keep in active context
            storage_dir: Directory to store session files
        """
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.active_context_limit = active_context_limit or self.DEFAULT_ACTIVE_CONTEXT

        # Context management
        self.context_mode = ContextMode.ACTIVE_SESSION
        self.conversation_history = []
        self.session_manager = SessionManager(storage_dir)

        # Load existing session if available
        self._load_existing_session()

    def _load_existing_session(self):
        """Load existing session data if available."""
        session_data = self.session_manager.load_session(self.session_id)
        if session_data:
            self.conversation_history = session_data.get('conversation_history', [])
            print(f"📚 Loaded session '{self.session_id}' with {len(self.conversation_history)} previous exchanges")

    def _should_search(self, prompt: str) -> bool:
        """Determine if search should be enabled based on prompt content."""
        return any(keyword in prompt.lower() for keyword in self.SEARCH_KEYWORDS)

    def _estimate_token_count(self, text: str) -> int:
        """Rough estimation of token count (4 chars ≈ 1 token)."""
        return len(text) // 4

    def _build_context_active_session(self) -> str:
        """Build context using only recent exchanges (active session mode)."""
        if not self.conversation_history:
            return ""

        recent_history = self.conversation_history[-self.active_context_limit:]
        context = f"Recent conversation context ({len(recent_history)} exchanges):\n"

        for entry in recent_history:
            context += f"Student: {entry['question']}\nTutor: {entry['answer']}\n\n"

        return context

    def _build_context_full_history(self) -> str:
        """Build context using full conversation history with token management."""
        if not self.conversation_history:
            return ""

        context = f"Full conversation history ({len(self.conversation_history)} exchanges):\n"
        current_tokens = 0

        # Start with most recent and work backwards
        for entry in reversed(self.conversation_history):
            entry_text = f"Student: {entry['question']}\nTutor: {entry['answer']}\n\n"
            entry_tokens = self._estimate_token_count(entry_text)

            if current_tokens + entry_tokens > self.MAX_CONTEXT_TOKENS:
                context += "[Earlier conversation truncated due to length...]\n\n"
                break

            context = entry_text + context[len("Full conversation history"):]
            current_tokens += entry_tokens

        return context

    def _build_context_smart_summary(self) -> str:
        """Build context with recent exchanges + summary of older ones."""
        if not self.conversation_history:
            return ""

        # Recent exchanges
        recent_history = self.conversation_history[-self.DEFAULT_SUMMARY_CONTEXT:]
        context = f"Recent conversation ({len(recent_history)} exchanges):\n"

        for entry in recent_history:
            context += f"Student: {entry['question']}\nTutor: {entry['answer']}\n\n"

        # Summary of older exchanges if they exist
        older_history = self.conversation_history[:-self.DEFAULT_SUMMARY_CONTEXT]
        if older_history:
            topics = set()
            for entry in older_history:
                # Extract key topics (this is a simple approach - could be enhanced with NLP)
                question_words = entry['question'].lower().split()
                topics.update([word for word in question_words if len(word) > 4])

            context += f"Earlier topics covered: {', '.join(list(topics)[:10])}\n\n"

        return context

    def _build_context(self) -> str:
        """Build context based on current context mode."""
        if self.context_mode == ContextMode.ACTIVE_SESSION:
            return self._build_context_active_session()
        elif self.context_mode == ContextMode.FULL_HISTORY:
            return self._build_context_full_history()
        elif self.context_mode == ContextMode.SMART_SUMMARY:
            return self._build_context_smart_summary()
        else:
            return ""

    def set_context_mode(self, mode: str, active_limit: Optional[int] = None) -> str:
        """
        Switch context mode.

        Args:
            mode: One of 'active_session', 'full_history', 'smart_summary'
            active_limit: For active_session mode, number of exchanges to include

        Returns:
            Status message
        """
        valid_modes = [ContextMode.ACTIVE_SESSION, ContextMode.FULL_HISTORY, ContextMode.SMART_SUMMARY]

        if mode not in valid_modes:
            return f"❌ Invalid mode. Choose from: {', '.join(valid_modes)}"

        self.context_mode = mode

        if active_limit and mode == ContextMode.ACTIVE_SESSION:
            self.active_context_limit = active_limit

        mode_descriptions = {
            ContextMode.ACTIVE_SESSION: f"recent {self.active_context_limit} exchanges only",
            ContextMode.FULL_HISTORY: "full conversation history (token-limited)",
            ContextMode.SMART_SUMMARY: "recent exchanges + summary of older topics"
        }

        return f"✅ Context mode set to **{mode}** ({mode_descriptions[mode]})"

    def get_context_info(self) -> Dict:
        """Get information about current context settings."""
        return {
            'context_mode': self.context_mode,
            'active_context_limit': self.active_context_limit,
            'total_exchanges': len(self.conversation_history),
            'estimated_context_tokens': self._estimate_token_count(self._build_context()),
            'session_id': self.session_id
        }

    def ask(self, prompt: str, use_search: Optional[bool] = None, remember_context: bool = True) -> str:
        """
        Ask a question to the tutor with enhanced context management.

        Args:
            prompt: The student's question
            use_search: Force search on/off. If None, auto-determines based on content
            remember_context: Whether to remember this exchange
        """
        try:
            # Auto-determine search if not specified
            if use_search is None:
                use_search = self._should_search(prompt)

            # Build context based on current mode
            context = self._build_context() if remember_context else ""

            # Build full prompt
            full_prompt = f"{TUTOR_SYSTEM_PROMPT}\n\n{context}Student: {prompt}\n\nTutor:"

            # Generate response
            try:
                if use_search:
                    # Try with web search tool first
                    response = self.model.generate_content(
                        full_prompt,
                        tools=[{"web_search": {"enable_web_search": True}}]
                    )
                else:
                    response = self.model.generate_content(full_prompt)
            except Exception as search_error:
                if any(keyword in str(search_error).lower() for keyword in ["search", "grounding", "not supported", "tool"]):
                    # Fallback to generation without tools
                    print(f"Web search not available, falling back to standard generation: {search_error}")
                    response = self.model.generate_content(full_prompt)
                else:
                    raise search_error

            if response and response.text:
                answer = response.text

                # Store in conversation history and save session
                if remember_context:
                    self.conversation_history.append({
                        'question': prompt,
                        'answer': answer,
                        'used_search': use_search,
                        'timestamp': datetime.now().isoformat(),
                        'context_mode': self.context_mode
                    })

                    # Auto-save session
                    self.save_session()

                return answer
            else:
                return "❌ I received an empty response. Please try rephrasing your question."

        except Exception as e:
            print(f"Error with Gemini API: {e}")
            return f"❌ Sorry, I encountered an error: {str(e)}"

    def save_session(self, metadata: Dict = None):
        """Save current session to persistent storage with error handling."""
        try:
            session_metadata = {
                'context_mode': self.context_mode,
                'active_context_limit': self.active_context_limit,
                'model_name': self.model_name
            }
            if metadata:
                session_metadata.update(metadata)

            self.session_manager.save_session(self.session_id, self.conversation_history, session_metadata)
            
        except Exception as e:
            print(f"❌ Failed to save session '{self.session_id}': {e}")
            # Don't re-raise to avoid breaking the conversation flow
            return False
        
        return True

    def load_session(self, session_id: str) -> str:
        """Load a different session."""
        session_data = self.session_manager.load_session(session_id)
        if not session_data:
            return f"❌ Session '{session_id}' not found"

        self.session_id = session_id
        self.conversation_history = session_data.get('conversation_history', [])

        # Restore session settings
        metadata = session_data.get('metadata', {})
        if 'context_mode' in metadata:
            self.context_mode = metadata['context_mode']
        if 'active_context_limit' in metadata:
            self.active_context_limit = metadata['active_context_limit']

        return f"✅ Loaded session '{session_id}' with {len(self.conversation_history)} exchanges"

    def list_sessions(self) -> str:
        """List all available sessions."""
        sessions = self.session_manager.list_sessions()
        if not sessions:
            return "No saved sessions found."

        result = "📚 **Available Sessions:**\n"
        for session in sessions[:10]:  # Show max 10 recent sessions
            last_updated = session.get('last_updated', 'Unknown')
            if last_updated != 'Unknown':
                try:
                    dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    last_updated = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass

            result += f"• **{session['session_id']}** - {session['total_exchanges']} exchanges (Last: {last_updated})\n"

        return result

    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []

    def get_history_summary(self) -> str:
        """Get a summary of the conversation history."""
        if not self.conversation_history:
            return "No conversation history"

        total = len(self.conversation_history)
        with_search = sum(1 for entry in self.conversation_history if entry.get('used_search', False))

        # Get topic distribution (simple word frequency)
        all_questions = ' '.join([entry['question'] for entry in self.conversation_history])
        words = [word.lower() for word in all_questions.split() if len(word) > 4]
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1

        top_topics = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]

        summary = f"📊 **Session Summary:**\n"
        summary += f"• Total exchanges: {total}\n"
        summary += f"• Searches used: {with_search}\n"
        summary += f"• Current context mode: {self.context_mode}\n"
        summary += f"• Top topics: {', '.join([topic[0] for topic in top_topics])}\n"

        return summary

    # Convenience methods
    def ask_with_search(self, prompt: str) -> str:
        """Ask with search explicitly enabled."""
        return self.ask(prompt, use_search=True)

    def ask_without_search(self, prompt: str) -> str:
        """Ask with search explicitly disabled."""
        return self.ask(prompt, use_search=False)

# Demo function
def demo_context_management():
    """Demonstrate the enhanced context management features."""
    print("🎓 Enhanced LearnLM Context Management Demo")
    print("=" * 50)

    # Create tutor instance
    tutor = LearnLMTutor(session_id="demo_session")

    # Simulate some conversation
    questions = [
        "What is calculus?",
        "Can you explain derivatives?",
        "How do I find the derivative of x²?",
        "What about the chain rule?",
        "Can you give me practice problems?"
    ]

    print("Simulating conversation...")
    for i, question in enumerate(questions):
        print(f"\nQ{i+1}: {question}")
        # For demo, we'll just store mock responses
        mock_answer = f"This is a mock answer to question {i+1} about {question.lower()}"
        tutor.conversation_history.append({
            'question': question,
            'answer': mock_answer,
            'used_search': False,
            'timestamp': datetime.now().isoformat(),
            'context_mode': tutor.context_mode
        })

    print(f"\n📚 Conversation history: {len(tutor.conversation_history)} exchanges")

    # Demo different context modes
    print("\n🔄 Testing different context modes:")

    modes = [
        (ContextMode.ACTIVE_SESSION, 3),
        (ContextMode.SMART_SUMMARY, None),
        (ContextMode.FULL_HISTORY, None)
    ]

    for mode, limit in modes:
        if limit:
            result = tutor.set_context_mode(mode, limit)
        else:
            result = tutor.set_context_mode(mode)
        print(f"• {result}")

        context = tutor._build_context()
        token_count = tutor._estimate_token_count(context)
        print(f"  Context length: ~{token_count} tokens")

    # Demo session management
    print(f"\n💾 Saving session...")
    tutor.save_session()

    print(f"📋 Session info:")
    info = tutor.get_context_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    print(f"\n📖 {tutor.get_history_summary()}")

if __name__ == "__main__":
    demo_context_management()