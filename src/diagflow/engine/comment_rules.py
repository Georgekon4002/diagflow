"""
DiagFlow — Comment-Based Auto-Assignment & Exclusion Engine
===========================================================
Parses free-text comments from the secretariat to:
1. Detect active diagnostician name mentions (including consonant skeletons like
   'ΝΤΣΚ', inflected forms, accented names like 'Νάτσικα', and typos like 'Νατσκα').
2. Detect negative exclusions when preceded by 'ΟΧΙ' / 'όχι' / 'ΜΗΝ' / 'NOT' etc.,
   which excludes the diagnostician from suggestions and suppresses all other auto-assign rules.
"""

import re
import unicodedata

# Greek vowels used for consonant skeleton extraction
GREEK_VOWELS = set("ΑΕΗΙΟΥΩ")
LATIN_VOWELS = set("AEIOUY")

# Negation words / phrases in Greek and English
NEGATION_WORDS = {
    "ΟΧΙ", "OXI", "ΜΗ", "ΜΗΝ", "NOT", "NO", "ΕΚΤΟΣ", "ΑΠΟΚΛΕΙΣΜΟΣ", "ΑΚΥΡΟ", "ΧΩΡΙΣ"
}

# Clause separator tokens that reset negation scope
CLAUSE_SEPARATORS = {
    "-", ",", ";", ".", "!", "?", "/", "\\", "ΑΛΛΑ", "ΜΟΝΟ", "MONO", "ΑΝΤΙ", "ANTI",
    "ΚΑΙ", "ΠΑΡΑΚΑΛΩ", "PLEASE", "ONLY", "BUT", "ANTI", "->", "=>"
}

# Stopwords between negation and diagnostician name (e.g. "ΟΧΙ ΣΕ ΝΑΤΣΙΚΑ", "ΟΧΙ ΣΤΟΝ ΜΠΕΡΕΤΗ")
NEGATION_LINK_WORDS = {
    "ΣΕ", "ΣΤΟΝ", "ΣΤΗΝ", "ΣΤΟ", "ΣΤΟΥΣ", "ΣΤΙΣ", "ΓΙΑ", "ΑΠΟ", "ΤΟΝ", "ΤΗΝ", "ΤΟ", "TO", "FOR", "IN"
}


def normalize_greek_text(text: str) -> str:
    """
    Normalizes a Greek or Greeklish string:
    - Strips accents (tonous, dialytika)
    - Converts to uppercase
    - Standardizes final sigma (ς -> Σ)
    """
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    res = stripped.upper().replace("ς", "Σ")
    return res


def extract_consonant_skeleton(word: str) -> str:
    """
    Extracts the consonant skeleton of a Greek or Latin word (strips all vowels).
    e.g. 'ΝΑΤΣΙΚΑ' -> 'ΝΤΣΚ', 'ΜΠΕΡΕΤΗΣ' -> 'ΜΠΡΤΣ'
    """
    norm = normalize_greek_text(word)
    return "".join(c for c in norm if c not in GREEK_VOWELS and c not in LATIN_VOWELS and c.isalpha())


def transliterate_greeklish_to_greek(text: str) -> str:
    """
    Transliterates common Greeklish spellings to Greek uppercase.
    """
    upper = text.upper()
    mapping = [
        ("TH", "Θ"), ("CH", "Χ"), ("PS", "Ψ"), ("KS", "Ξ"), ("PH", "Φ"),
        ("MP", "ΜΠ"), ("NT", "ΝΤ"), ("OU", "ΟΥ"),
        ("A", "Α"), ("B", "Β"), ("V", "Β"), ("G", "Γ"), ("D", "Δ"),
        ("E", "Ε"), ("Z", "Ζ"), ("H", "Η"), ("I", "Ι"), ("K", "Κ"),
        ("L", "Λ"), ("M", "Μ"), ("N", "Ν"), ("X", "Ξ"), ("O", "Ο"),
        ("P", "Π"), ("R", "Ρ"), ("S", "Σ"), ("T", "Τ"), ("Y", "Υ"),
        ("U", "Υ"), ("F", "Φ"), ("W", "Ω"), ("C", "Κ"), ("J", "ΤΖ")
    ]
    res = upper
    for lat, grk in mapping:
        res = res.replace(lat, grk)
    return res


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes the Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def build_diagnostician_patterns(diagnosticians: list[dict]) -> list[dict]:
    """
    Builds a comprehensive search profile for each active diagnostician.
    Includes:
    - Full surname and first name
    - Declension variations (nominative, accusative, genitive)
    - Consonant skeletons (e.g. 'ΝΤΣΚ' for 'ΝΑΤΣΙΚΑ')
    - Stem patterns (e.g. 'ΝΑΤΣΙΚ', 'ΜΠΕΡΕΤ')
    - Latin transliterations
    """
    profiles = []

    for d in diagnosticians:
        if not d.get("active", True):
            continue

        raw_name = d.get("name", "").strip()
        if not raw_name:
            continue

        norm_name = normalize_greek_text(raw_name)
        parts = [p.strip() for p in re.split(r"[\s\-_]+", norm_name) if p.strip()]
        if not parts:
            continue

        surname = parts[0]
        first_name = parts[1] if len(parts) > 1 else ""

        exact_keys = set()
        exact_keys.add(surname)
        if first_name and len(first_name) >= 3:
            exact_keys.add(first_name)

        # Standard Greek surname declension endings
        stem = surname
        for suffix in ("ΟΣ", "ΗΣ", "ΑΣ", "ΟΥ", "ΕΑΣ", "ΗΣ", "ΩΝ"):
            if surname.endswith(suffix) and len(surname) > len(suffix) + 2:
                stem = surname[:-len(suffix)]
                exact_keys.add(stem)
                exact_keys.add(stem + "Α")
                exact_keys.add(stem + "Η")
                exact_keys.add(stem + "Ο")
                exact_keys.add(stem + "ΟΥ")
                exact_keys.add(stem + "Ε")
                exact_keys.add(stem + "ΕΣ")
                exact_keys.add(stem + "ΟΙ")
                exact_keys.add(stem + "ΩΝ")
                break
        else:
            if surname.endswith("Α") and len(surname) > 3:
                stem = surname[:-1]
                exact_keys.add(stem)
                exact_keys.add(stem + "ΑΣ")
                exact_keys.add(stem + "ΕΣ")
            elif surname.endswith("Η") and len(surname) > 3:
                stem = surname[:-1]
                exact_keys.add(stem)
                exact_keys.add(stem + "ΗΣ")

        # Consonant skeleton
        skeletons = set()
        s_skel = extract_consonant_skeleton(surname)
        if len(s_skel) >= 3:
            skeletons.add(s_skel)
            if s_skel.endswith("Σ") and len(s_skel) > 3:
                skeletons.add(s_skel[:-1])

        stem_skel = extract_consonant_skeleton(stem)
        if len(stem_skel) >= 3:
            skeletons.add(stem_skel)

        profiles.append({
            "id": d["id"],
            "name": d["name"],
            "surname": surname,
            "stem": stem,
            "exact_keys": exact_keys,
            "skeletons": skeletons,
        })

    return profiles


def parse_comment_diagnosticians(
    comment_text: str,
    diagnosticians: list[dict],
) -> tuple[dict | None, set[int]]:
    """
    Parses an exam's comment text to find active diagnosticians mentioned.

    Returns:
        tuple (matched_diagnostician, excluded_diagnostician_ids):
        - matched_diagnostician: dict with 'id', 'name', 'matched_token' if an active
          diagnostician was positively assigned, else None.
        - excluded_diagnostician_ids: set of diagnostician IDs that were explicitly
          excluded (e.g. 'ΟΧΙ ΝΑΤΣΙΚΑ').
    """
    if not comment_text or not comment_text.strip():
        return None, set()

    norm_comment = normalize_greek_text(comment_text)
    translit_comment = transliterate_greeklish_to_greek(comment_text)

    # Tokenize words while preserving punctuation tokens like '-' or ','
    raw_tokens = [t for t in re.findall(r"[\w]+|[^\w\s]", norm_comment) if t.strip()]
    translit_tokens = [t for t in re.findall(r"[\w]+|[^\w\s]", translit_comment) if t.strip()]

    profiles = build_diagnostician_patterns(diagnosticians)

    matched_diagnostician: dict | None = None
    excluded_ids: set[int] = set()

    # Track negation state linearly through tokens
    in_negation = False
    negation_distance = 0

    for i, tok in enumerate(raw_tokens):
        tr_tok = translit_tokens[i] if i < len(translit_tokens) else tok

        # Check for negation starter token (e.g. "ΟΧΙ", "ΜΗΝ", "NOT")
        if tok in NEGATION_WORDS or tr_tok in NEGATION_WORDS:
            in_negation = True
            negation_distance = 0
            continue

        # Check for clause separators resetting negation
        if tok in CLAUSE_SEPARATORS or tr_tok in CLAUSE_SEPARATORS:
            in_negation = False
            negation_distance = 0
            continue

        if in_negation:
            negation_distance += 1
            # If we went more than 3 non-link words without finding a name, reset negation
            if negation_distance > 3 and tok not in NEGATION_LINK_WORDS and tr_tok not in NEGATION_LINK_WORDS:
                in_negation = False

        # Check if current token matches any active diagnostician
        matched_profile = None
        matched_tok_str = tok

        for prof in profiles:
            diag_id = prof["id"]
            exact_keys = prof["exact_keys"]
            skeletons = prof["skeletons"]
            stem = prof["stem"]
            surname = prof["surname"]

            for check_tok in (tok, tr_tok):
                if not check_tok or len(check_tok) < 3:
                    continue

                # 1. Exact surname / name / declension match
                if check_tok in exact_keys:
                    matched_profile = prof
                    matched_tok_str = check_tok
                    break

                # 2. Skeleton match (e.g. 'ΝΤΣΚ', 'ΜΠΡΤ')
                if check_tok in skeletons:
                    matched_profile = prof
                    matched_tok_str = check_tok
                    break

                # 3. Stem prefix match
                if len(stem) >= 5 and check_tok.startswith(stem):
                    matched_profile = prof
                    matched_tok_str = check_tok
                    break

                # 4. Levenshtein edit distance for typos (e.g. 'ΝΑΤΣΚΑ' vs 'ΝΑΤΣΙΚΑ')
                if len(surname) >= 5 and len(check_tok) >= 5:
                    if abs(len(check_tok) - len(surname)) <= 1:
                        if levenshtein_distance(check_tok, surname) <= 1:
                            matched_profile = prof
                            matched_tok_str = check_tok
                            break
                        if levenshtein_distance(check_tok, stem) <= 1:
                            matched_profile = prof
                            matched_tok_str = check_tok
                            break

            if matched_profile:
                break

        if matched_profile:
            diag_id = matched_profile["id"]
            if in_negation:
                excluded_ids.add(diag_id)
                # Negation has been consumed by this diagnostician match
                in_negation = False
            else:
                if matched_diagnostician is None and diag_id not in excluded_ids:
                    matched_diagnostician = {
                        "id": diag_id,
                        "name": matched_profile["name"],
                        "matched_token": matched_tok_str,
                    }

    # If the positively matched candidate is in the excluded set, discard positive match
    if matched_diagnostician and matched_diagnostician["id"] in excluded_ids:
        matched_diagnostician = None

    return matched_diagnostician, excluded_ids
