"""
Context Manager — resume and job description context for personalized answers.
Parses PDF, DOCX, and TXT files. Stores context for prompt injection.
"""

import json
from pathlib import Path

CONTEXT_FILE = Path.home() / ".audio_detector_context.json"

# Lazy imports for optional dependencies
PYPDF2_AVAILABLE = False
DOCX_AVAILABLE = False

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    pass

try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    pass


def load_context():
    """Load saved context (resume + job description) from disk.

    Returns:
        dict with keys: resume_text, resume_file, job_description
    """
    defaults = {
        "resume_text": "",
        "resume_file": "",
        "job_description": "",
    }
    try:
        if CONTEXT_FILE.exists():
            with open(CONTEXT_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            defaults.update(saved)
    except Exception as e:
        print(f"[ContextManager] Error loading context: {e}")
    return defaults


def save_context(context):
    """Save context to disk."""
    try:
        with open(CONTEXT_FILE, 'w', encoding='utf-8') as f:
            json.dump(context, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ContextManager] Error saving context: {e}")


def parse_resume(file_path):
    """Parse a resume file and extract text content.

    Supports: .pdf, .docx, .doc, .txt

    Args:
        file_path: Path to the resume file.

    Returns:
        Extracted text string, or error message.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == '.txt':
        return _parse_txt(path)
    elif suffix == '.pdf':
        return _parse_pdf(path)
    elif suffix in ('.docx', '.doc'):
        return _parse_docx(path)
    else:
        return f"Unsupported file format: {suffix}. Use .pdf, .docx, or .txt"


def _parse_txt(path):
    """Parse plain text file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except UnicodeDecodeError:
        try:
            with open(path, 'r', encoding='latin-1') as f:
                return f.read().strip()
        except Exception as e:
            return f"Error reading text file: {e}"
    except Exception as e:
        return f"Error reading text file: {e}"


def _parse_pdf(path):
    """Parse PDF file using PyPDF2."""
    if not PYPDF2_AVAILABLE:
        return "Error: PyPDF2 not installed. Run: pip install PyPDF2"
    try:
        text_parts = []
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return '\n'.join(text_parts).strip()
    except Exception as e:
        return f"Error reading PDF: {e}"


def _parse_docx(path):
    """Parse DOCX file using python-docx."""
    if not DOCX_AVAILABLE:
        return "Error: python-docx not installed. Run: pip install python-docx"
    try:
        doc = docx.Document(str(path))
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        return '\n'.join(text_parts).strip()
    except Exception as e:
        return f"Error reading DOCX: {e}"


def build_context_prompt(context, max_chars=2000):
    """Build a context string for injection into the LLM system prompt.

    Truncates long texts to avoid exceeding token limits.

    Args:
        context: dict from load_context()
        max_chars: Maximum characters per section.

    Returns:
        Context string to append to system prompt, or empty string.
    """
    parts = []

    resume = context.get("resume_text", "").strip()
    if resume:
        truncated = resume[:max_chars]
        if len(resume) > max_chars:
            truncated += "... [truncated]"
        parts.append(
            f"CANDIDATE'S RESUME/BACKGROUND:\n{truncated}"
        )

    jd = context.get("job_description", "").strip()
    if jd:
        truncated = jd[:max_chars]
        if len(jd) > max_chars:
            truncated += "... [truncated]"
        parts.append(
            f"TARGET JOB DESCRIPTION:\n{truncated}"
        )

    if parts:
        return (
            "\n\n--- PERSONALIZATION CONTEXT ---\n"
            "Use the following background to tailor your answers. "
            "Reference the candidate's experience when relevant, and align answers "
            "with the job requirements.\n\n"
            + "\n\n".join(parts)
            + "\n--- END CONTEXT ---\n"
        )
    return ""


def get_resume_summary(context):
    """Get a brief summary string for UI display.

    Returns:
        e.g. "✅ Resume loaded (324 words)" or "No resume loaded"
    """
    resume = context.get("resume_text", "").strip()
    if resume:
        word_count = len(resume.split())
        filename = context.get("resume_file", "")
        name_part = Path(filename).name if filename else "uploaded"
        return f"✅ {name_part} ({word_count} words)"
    return "No resume loaded"


def get_jd_summary(context):
    """Get a brief summary string for JD display.

    Returns:
        e.g. "✅ JD loaded (156 words)" or "No job description"
    """
    jd = context.get("job_description", "").strip()
    if jd:
        word_count = len(jd.split())
        return f"✅ Job description ({word_count} words)"
    return "No job description"
