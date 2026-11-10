"""Fixed lines that never go through Evon.

The AI disclosure is spoken to both people at the start of every call. Keeping it as fixed
text means it is always said, always says the same thing, and Timbre's output is cached
after the first call, so it costs credits only once per language and voice.

Have a native speaker check each line before your demo.
"""
from __future__ import annotations

DISCLOSURE: dict[str, str] = {
    "en-IN": "This call is being translated by an AI assistant.",
    "hi-IN": "इस कॉल का अनुवाद AI द्वारा किया जा रहा है।",
    "mr-IN": "हा कॉल AI द्वारे अनुवादित केला जात आहे.",
    "bn-IN": "এই কলটি AI-এর মাধ্যমে অনুবাদ করা হচ্ছে।",
    "pa-IN": "ਇਸ ਕਾਲ ਦਾ ਅਨੁਵਾਦ AI ਰਾਹੀਂ ਕੀਤਾ ਜਾ ਰਿਹਾ ਹੈ।",
    "gu-IN": "આ કૉલનો અનુવાદ AI દ્વારા થઈ રહ્યો છે.",
    "ta-IN": "இந்த அழைப்பு AI மூலம் மொழிபெயர்க்கப்படுகிறது.",
    "te-IN": "ఈ కాల్ AI ద్వారా అనువదించబడుతోంది.",
    "kn-IN": "ಈ ಕರೆಯನ್ನು AI ಮೂಲಕ ಅನುವಾದಿಸಲಾಗುತ್ತಿದೆ.",
    "ml-IN": "ഈ കോൾ AI വഴി വിവർത്തനം ചെയ്യപ്പെടുന്നു.",
}


def disclosure(code: str) -> str:
    return DISCLOSURE.get(code, DISCLOSURE["en-IN"])


# Asked after delivery when the saved pin was wrong. Fixed text, so it always arrives in the customer's language.
PIN_FIX: dict[str, str] = {
    "en-IN": "Shall we move your saved location to the correct building?",
    "hi-IN": "क्या हम आपकी सेव की हुई लोकेशन को सही बिल्डिंग पर कर दें?",
    "mr-IN": "तुमचं सेव्ह केलेलं लोकेशन योग्य इमारतीवर हलवू का?",
    "bn-IN": "আপনার সেভ করা লোকেশনটা কি সঠিক বিল্ডিংয়ে সরিয়ে দেব?",
    "pa-IN": "ਕੀ ਅਸੀਂ ਤੁਹਾਡੀ ਸੇਵ ਕੀਤੀ ਲੋਕੇਸ਼ਨ ਨੂੰ ਸਹੀ ਬਿਲਡਿੰਗ 'ਤੇ ਕਰ ਦੇਈਏ?",
    "gu-IN": "તમારું સેવ કરેલું લોકેશન સાચી બિલ્ડિંગ પર ખસેડી દઈએ?",
    "ta-IN": "உங்கள் சேமித்த இடத்தை சரியான கட்டிடத்திற்கு மாற்றலாமா?",
    "te-IN": "మీ సేవ్ చేసిన లొకేషన్‌ను సరైన బిల్డింగ్‌కు మార్చమంటారా?",
    "kn-IN": "ನಿಮ್ಮ ಉಳಿಸಿದ ಸ್ಥಳವನ್ನು ಸರಿಯಾದ ಕಟ್ಟಡಕ್ಕೆ ಬದಲಾಯಿಸೋಣವೇ?",
    "ml-IN": "നിങ്ങളുടെ സേവ് ചെയ്ത ലൊക്കേഷൻ ശരിയായ കെട്ടിടത്തിലേക്ക് മാറ്റട്ടെ?",
}


def pin_fix(code: str) -> str:
    return PIN_FIX.get(code, PIN_FIX["en-IN"])
