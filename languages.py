"""
Language Registry — all Whisper-supported languages with question word detection.
"""

# Full list of Whisper-supported languages with metadata
# Format: (display_name, iso_code, whisper_code, question_words)
LANGUAGES = [
    # Most commonly used (top of list)
    ("English", "en", "en", ["what", "where", "when", "why", "how", "who", "which", "whom",
                              "can", "could", "would", "should", "is", "are", "do", "does", "did",
                              "will", "shall", "may", "might", "have", "has", "had"]),
    ("Ukrainian", "uk", "uk", ["що", "де", "коли", "чому", "як", "хто", "який", "яка", "яке", "які",
                                "чи", "скільки", "котрий", "куди", "звідки", "навіщо", "відколи"]),
    ("Russian", "ru", "ru", ["что", "где", "когда", "почему", "как", "кто", "какой", "какая", "какое",
                              "ли", "сколько", "куда", "откуда", "зачем"]),
    ("German", "de", "de", ["was", "wo", "wann", "warum", "wie", "wer", "welch", "welche", "welcher",
                             "wieso", "weshalb", "woher", "wohin", "wieviel"]),
    ("French", "fr", "fr", ["que", "quoi", "où", "quand", "pourquoi", "comment", "qui", "quel", "quelle",
                             "combien", "est-ce"]),
    ("Spanish", "es", "es", ["qué", "dónde", "cuándo", "por qué", "cómo", "quién", "cuál",
                              "cuánto", "cuánta", "adónde"]),
    ("Polish", "pl", "pl", ["co", "gdzie", "kiedy", "dlaczego", "jak", "kto", "który", "która", "które",
                             "ile", "skąd", "dokąd", "po co", "czy"]),
    ("Chinese", "zh", "zh", ["什么", "哪里", "什么时候", "为什么", "怎么", "谁", "哪个", "多少", "吗", "呢"]),
    ("Japanese", "ja", "ja", ["何", "どこ", "いつ", "なぜ", "どう", "誰", "どの", "いくつ", "か", "ですか"]),

    # Additional languages (alphabetical)
    ("Afrikaans", "af", "af", ["wat", "waar", "wanneer", "waarom", "hoe", "wie"]),
    ("Arabic", "ar", "ar", ["ما", "ماذا", "أين", "متى", "لماذا", "كيف", "من", "كم", "هل"]),
    ("Armenian", "hy", "hy", ["ինչ", "որտեղ", "երբ", "ինusage", "ինչպես", "ով"]),
    ("Azerbaijani", "az", "az", ["nə", "hara", "nə vaxt", "niyə", "necə", "kim"]),
    ("Belarusian", "be", "be", ["што", "дзе", "калі", "чаму", "як", "хто"]),
    ("Bosnian", "bs", "bs", ["šta", "gdje", "kada", "zašto", "kako", "ko"]),
    ("Bulgarian", "bg", "bg", ["какво", "къде", "кога", "защо", "как", "кой"]),
    ("Catalan", "ca", "ca", ["què", "on", "quan", "per què", "com", "qui"]),
    ("Croatian", "hr", "hr", ["što", "gdje", "kada", "zašto", "kako", "tko"]),
    ("Czech", "cs", "cs", ["co", "kde", "kdy", "proč", "jak", "kdo", "který", "kolik"]),
    ("Danish", "da", "da", ["hvad", "hvor", "hvornår", "hvorfor", "hvordan", "hvem"]),
    ("Dutch", "nl", "nl", ["wat", "waar", "wanneer", "waarom", "hoe", "wie", "welke"]),
    ("Estonian", "et", "et", ["mis", "kus", "millal", "miks", "kuidas", "kes"]),
    ("Finnish", "fi", "fi", ["mitä", "missä", "milloin", "miksi", "miten", "kuka"]),
    ("Galician", "gl", "gl", ["que", "onde", "cando", "por que", "como", "quen"]),
    ("Georgian", "ka", "ka", ["რა", "სად", "როდის", "რატომ", "როგორ", "ვინ"]),
    ("Greek", "el", "el", ["τι", "πού", "πότε", "γιατί", "πώς", "ποιος"]),
    ("Hebrew", "he", "he", ["מה", "איפה", "מתי", "למה", "איך", "מי"]),
    ("Hindi", "hi", "hi", ["क्या", "कहाँ", "कब", "क्यों", "कैसे", "कौन", "कितना"]),
    ("Hungarian", "hu", "hu", ["mi", "hol", "mikor", "miért", "hogyan", "ki", "melyik"]),
    ("Icelandic", "is", "is", ["hvað", "hvar", "hvenær", "af hverju", "hvernig", "hver"]),
    ("Indonesian", "id", "id", ["apa", "dimana", "kapan", "mengapa", "bagaimana", "siapa"]),
    ("Italian", "it", "it", ["cosa", "dove", "quando", "perché", "come", "chi", "quale", "quanto"]),
    ("Kannada", "kn", "kn", ["ಏನು", "ಎಲ್ಲಿ", "ಯಾವಾಗ", "ಏಕೆ", "ಹೇಗೆ", "ಯಾರು"]),
    ("Kazakh", "kk", "kk", ["не", "қайда", "қашан", "неге", "қалай", "кім"]),
    ("Korean", "ko", "ko", ["무엇", "어디", "언제", "왜", "어떻게", "누구"]),
    ("Latvian", "lv", "lv", ["kas", "kur", "kad", "kāpēc", "kā", "kurš"]),
    ("Lithuanian", "lt", "lt", ["kas", "kur", "kada", "kodėl", "kaip", "kuris"]),
    ("Macedonian", "mk", "mk", ["што", "каде", "кога", "зошто", "како", "кој"]),
    ("Malay", "ms", "ms", ["apa", "dimana", "bila", "mengapa", "bagaimana", "siapa"]),
    ("Marathi", "mr", "mr", ["काय", "कुठे", "केव्हा", "का", "कसे", "कोण"]),
    ("Mongolian", "mn", "mn", ["юу", "хаана", "хэзээ", "яагаад", "яаж", "хэн"]),
    ("Norwegian", "no", "no", ["hva", "hvor", "når", "hvorfor", "hvordan", "hvem"]),
    ("Persian", "fa", "fa", ["چه", "کجا", "کی", "چرا", "چگونه", "کي"]),
    ("Portuguese", "pt", "pt", ["o que", "onde", "quando", "por que", "como", "quem", "qual", "quanto"]),
    ("Romanian", "ro", "ro", ["ce", "unde", "când", "de ce", "cum", "cine", "care"]),
    ("Serbian", "sr", "sr", ["шта", "где", "када", "зашто", "како", "ко"]),
    ("Slovak", "sk", "sk", ["čo", "kde", "kedy", "prečo", "ako", "kto", "ktorý"]),
    ("Slovenian", "sl", "sl", ["kaj", "kje", "kdaj", "zakaj", "kako", "kdo"]),
    ("Swedish", "sv", "sv", ["vad", "var", "när", "varför", "hur", "vem", "vilken"]),
    ("Tamil", "ta", "ta", ["என்ன", "எங்கே", "எப்போது", "ஏன்", "எப்படி", "யார்"]),
    ("Thai", "th", "th", ["อะไร", "ที่ไหน", "เมื่อไร", "ทำไม", "อย่างไร", "ใคร"]),
    ("Turkish", "tr", "tr", ["ne", "nerede", "ne zaman", "neden", "nasıl", "kim", "hangi"]),
    ("Urdu", "ur", "ur", ["کیا", "کہاں", "کب", "کیوں", "کیسے", "کون"]),
    ("Vietnamese", "vi", "vi", ["gì", "đâu", "khi nào", "tại sao", "như thế nào", "ai"]),
    ("Welsh", "cy", "cy", ["beth", "ble", "pryd", "pam", "sut", "pwy"]),
]


def get_language_names():
    """Return list of display names for all supported languages."""
    return [lang[0] for lang in LANGUAGES]


def get_language_by_name(name):
    """Look up language tuple by display name.

    Returns:
        (display_name, iso_code, whisper_code, question_words) or None.
    """
    for lang in LANGUAGES:
        if lang[0] == name:
            return lang
    return None


def get_question_words(language_name):
    """Get question words for a given language.

    Falls back to empty list if language not found.
    """
    lang = get_language_by_name(language_name)
    if lang:
        return lang[3]
    return []


def get_all_question_words():
    """Get a combined set of all question words across all languages."""
    words = set()
    for lang in LANGUAGES:
        words.update(lang[3])
    return words


def get_whisper_code(language_name):
    """Get the Whisper language code for a given language display name."""
    lang = get_language_by_name(language_name)
    if lang:
        return lang[2]
    return "en"


def get_iso_code(language_name):
    """Get the ISO language code for a given language display name."""
    lang = get_language_by_name(language_name)
    if lang:
        return lang[1]
    return "en"
