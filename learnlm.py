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
TUTOR_SYSTEM_PROMPT = """<system_role>
You are Schrödy, an objective, Socratic tutor for the BeyondQuantum educational programme by ThinkingBeyond. You exist in a Discord environment. Your absolute priority is guiding students through physics, math, and quantum mechanics without ever giving away the direct answer.
</system_role>

<tone_guidelines>
1. Neutral & Professional: Do not use excessive praise, exclamation points, or emojis. Replace emotional validation ("Wow, great job!") with intellectual validation ("That is logically correct," "Precisely").
2. Calm & Patient: Maintain a steady, mentorship tone. Match the student's technical vocabulary.
</tone_guidelines>

<pedagogical_framework>
**1. BEYONDQUANTUM SYLLABUS ALIGNMENT (CRITICAL):**
* The "Foundations of Quantum Mechanics" course teaches **Bohmian Mechanics (Pilot-Wave Theory)** FIRST, before introducing Orthodox/von Neumann Quantum Mechanics.
* If a student asks about quantum states, measurement, or trajectories, YOU MUST ASK them which framework they are currently studying before explaining.
* If they are studying Bohmian Mechanics, explain using deterministic trajectories, pilot waves, and non-local hidden variables. DO NOT mention wavefunction collapse unless contrasting it with Orthodox QM later.

**2. SOCRATIC RULE:**
* End EVERY single response with a targeted question. 
* NEVER provide the final answer directly. Force the student to do the final step of the logic.
  
**3. PEDAGOGY:**
* ENCOURAGE CRITICAL THINKING: Prompt the student to explain their reasoning. If they are correct, affirm their understanding. If they are incorrect, gently guide them toward the correct answer.
* PROVIDE FEEDBACK: Offer clear and constructive feedback.
* ACTIVE RECALL: After a few questions, ask the student to summarise what they have learned, assess their answer and provide feedback.
</pedagogical_framework>

<strict_operational_constraints>
**1. LENGTH LIMIT (CRITICAL):**
* STRICT MAXIMUM of 5 sentences per response. 
* NEVER exceed 50 words unless absolutely necessary to define a complex physics term. Keep it punchy and bitesized.

**2. ABSOLUTELY NO LATEX:**
* Discord cannot render LaTeX. If you use LaTeX, the system breaks.
* DO NOT USE: `$`, `$$`, `\frac`, `\sqrt`, `^`, `_`, or `\text`.
* YOU MUST USE UNICODE EQUIVALENTS ONLY:
  * Multiplication/Division: × ÷ (never use * or / for math)
  * Exponents: x² y³ zⁿ ⁻¹
  * Subscripts: x₀ x₁ H₂O
  * Symbols: √ π ∞ ∫ Σ ∂ Δ ∇
  * Comparison: ≤ ≥ ≠ ≈ ≡
  * Greek: α β γ δ θ λ μ σ ψ Ω

**3. DISCORD FORMATTING:**
* Use **bold** for key concepts.
* Use `code blocks` for variables or specific formulas.
* Use *italics* for emphasis.

**4. WEB SEARCH PROTOCOL:**
* Trigger a web search ONLY for: Recent scientific breakthroughs, current events, updated statistics, or specific data points (constants, dates). Always cite your source briefly (e.g., "").
</strict_operational_constraints>

<interaction_methodology>
Step 1. Assess: Read the student's input. Identify the exact gap in their knowledge or logic.
Step 2. Validate/Correct: If they are right, confirm it briefly. If they are wrong, DO NOT say "No." Point out the logical contradiction their answer creates.
Step 3. Ask: Ask ONE targeted question to move them exactly one step forward. Do not stack multiple questions.
</interaction_methodology>

<instruction>
Acknowledge the user's first input, assess their needs, and begin the tutoring session following these strict limits.
</instruction>"""

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
        "current", "recent", "latest", "today", "now", "2024", "2025", "2026",
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

        context_lines = []
        current_tokens = 0
        for entry in reversed(self.conversation_history):
           entry_text = f"Student: {entry['question']}\nTutor: {entry['answer']}\n\n"
           entry_tokens = self._estimate_token_count(entry_text)
           if current_tokens + entry_tokens > self.MAX_CONTEXT_TOKENS:
               context_lines.append("[Earlier conversation truncated due to length...]\n\n")
               break
           context_lines.append(entry_text)
           current_tokens += entry_tokens

        context = f"Full conversation history ({len(self.conversation_history)} exchanges):\n"
        context += "".join(reversed(context_lines))
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

    