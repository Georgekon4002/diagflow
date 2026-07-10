"""
DiagFlow — LLM Comment Parser

Parses free-text secretariat comments/remarks using an LLM to extract
structured assignment instructions (exclusions, direct assignments).

Examples of comments it should handle:
- "ΟΧΙ ΝΑΤΣΙΚΑ" → exclude Νάτσικα
- "ΝΑ ΤΟ ΠΑΡΕΙ Ο ΠΑΠΑΔΟΠΟΥΛΟΣ" → direct assign to Παπαδόπουλος
- "Επείγον, ΟΧΙ ΝΑΤΣΙΚΑ" → exclude Νάτσικα, mark urgent
- "Ασθενής ζητά τον Κωνσταντίνου" → direct assign to Κωνσταντίνου
- "ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ" → Παμακάριστος on-call handling
- "" (empty) → no action

The LLM returns structured JSON, which is then used by the hard filters.
"""

from typing import Optional

import structlog

from diagflow.config import settings

logger = structlog.get_logger(__name__)

# System prompt for the LLM
COMMENT_PARSER_SYSTEM_PROMPT = """Είσαι ένα σύστημα ανάλυσης σχολίων γραμματείας ακτινοδιαγνωστικού κέντρου.

Αναλύεις σχόλια/παρατηρήσεις που γράφει η γραμματεία στο σύστημα Slis κατά την ανάθεση εξετάσεων CT/MRI σε ακτινοδιαγνώστες.

Τα σχόλια μπορεί να περιέχουν:
1. ΕΞΑΙΡΕΣΕΙΣ: "ΟΧΙ [ΟΝΟΜΑ]" — σημαίνει να μην ανατεθεί σε αυτόν τον ακτινοδιαγνώστη
2. ΑΜΕΣΗ ΑΝΑΘΕΣΗ: "ΝΑ ΤΟ ΠΑΡΕΙ Ο/Η [ΟΝΟΜΑ]" ή "Ο/Η [ΟΝΟΜΑ] ΝΑ ΤΟ ΔΩΣΕΙ" — σημαίνει να ανατεθεί σε αυτόν
3. ΕΦΗΜΕΡΙΑ: "ΕΦΗΜΕΡΙΑ ΠΑΜΜΑΚΑΡΙΣΤΟΥ" — ανάθεση στον εφημερεύοντα
4. ΟΥΔΕΤΕΡΟ: Σχόλια που δεν αφορούν ανάθεση (π.χ. "Επείγον", "Ελέγξτε αλλεργίες")

Απάντησε ΜΟΝΟ σε JSON μορφή:
{
  "exclude": ["ονομα1", "ονομα2"],      // Λίστα ονομάτων για εξαίρεση (κενή αν δεν υπάρχουν)
  "assign": "ονομα" | null,              // Όνομα για άμεση ανάθεση ή null
  "is_pamakristos": true | false,        // Αν αφορά εφημερία Παμμακαρίστου
  "is_urgent": true | false,             // Αν είναι επείγον
  "reasoning": "σύντομη εξήγηση"         // Γιατί αποφάσισες αυτό
}"""


async def parse_comment(comment: str, diagnostician_names: list[str]) -> dict:
    """
    Parse a free-text comment using the LLM.

    Args:
        comment: Raw comment text from the secretariat
        diagnostician_names: List of all diagnostician names (for matching)

    Returns:
        Parsed result dict with keys: exclude, assign, is_pamakristos, is_urgent, reasoning
    """
    # Empty comment → no action
    if not comment or not comment.strip():
        return {
            "exclude": [],
            "assign": None,
            "is_pamakristos": False,
            "is_urgent": False,
            "reasoning": "Κενό σχόλιο — δεν απαιτείται ενέργεια",
        }

    # Try keyword-based parsing first (fast, no API call needed)
    keyword_result = _keyword_parse(comment, diagnostician_names)
    if keyword_result:
        logger.info(
            "comment_parsed_by_keywords",
            comment=comment[:80],
            result=keyword_result,
        )
        return keyword_result

    # Fall back to LLM parsing for complex/ambiguous comments
    llm_result = await _llm_parse(comment, diagnostician_names)
    if llm_result:
        logger.info(
            "comment_parsed_by_llm",
            comment=comment[:80],
            result=llm_result,
        )
        return llm_result

    # Default: no action
    return {
        "exclude": [],
        "assign": None,
        "is_pamakristos": False,
        "is_urgent": False,
        "reasoning": f"Δεν αναγνωρίστηκε οδηγία ανάθεσης στο σχόλιο: '{comment[:80]}'",
    }


def _keyword_parse(comment: str, diagnostician_names: list[str]) -> Optional[dict]:
    """
    Fast keyword-based comment parsing.

    Handles the most common patterns without needing an LLM API call.
    Returns None if the comment is too complex for keyword matching.
    """
    upper = comment.upper().strip()

    exclude = []
    assign = None
    is_pamakristos = False
    is_urgent = False
    reasoning_parts = []

    # Check for Παμακάριστος on-call
    if "ΠΑΜΜΑΚΑΡΙΣΤΟ" in upper or "ΠΑΜΑΚΑΡΙΣΤΟ" in upper or "ΕΦΗΜΕΡΙΑ" in upper:
        is_pamakristos = True
        reasoning_parts.append("Αναγνωρίστηκε εφημερία Παμμακαρίστου")

    # Check for urgency
    if "ΕΠΕΙΓ" in upper or "URGENT" in upper:
        is_urgent = True
        reasoning_parts.append("Σημειώθηκε ως επείγον")

    # Check for exclusions: "ΟΧΙ [NAME]"
    for name in diagnostician_names:
        # Extract surname for matching
        surname = name.split()[0].upper() if name else ""
        if surname and f"ΟΧΙ {surname}" in upper:
            exclude.append(name)
            reasoning_parts.append(f"Εξαίρεση: {name}")

        # Check for direct assignment: "ΝΑ ΤΟ ΠΑΡΕΙ Ο/Η [NAME]" or similar
        if surname and (
            f"ΝΑ ΤΟ ΠΑΡΕΙ" in upper and surname in upper
            or f"ΝΑ ΤΟ ΔΩΣΕΙ" in upper and surname in upper
            or f"ΖΗΤΑ ΤΟΝ {surname}" in upper
            or f"ΖΗΤΑ ΤΗΝ {surname}" in upper
            or f"ΖΗΤΑΕΙ ΤΟΝ {surname}" in upper
            or f"ΖΗΤΑΕΙ ΤΗΝ {surname}" in upper
        ):
            assign = name
            reasoning_parts.append(f"Άμεση ανάθεση: {name}")

    # Only return if we found something meaningful
    if exclude or assign or is_pamakristos:
        return {
            "exclude": exclude,
            "assign": assign,
            "is_pamakristos": is_pamakristos,
            "is_urgent": is_urgent,
            "reasoning": " | ".join(reasoning_parts) if reasoning_parts else "Keyword match",
        }

    # If only urgency was found but nothing about assignment, still return
    if is_urgent:
        return {
            "exclude": [],
            "assign": None,
            "is_pamakristos": False,
            "is_urgent": True,
            "reasoning": "Σημειώθηκε ως επείγον — δεν υπάρχει οδηγία ανάθεσης",
        }

    return None  # Comment too complex for keywords


async def _llm_parse(comment: str, diagnostician_names: list[str]) -> Optional[dict]:
    """
    Parse comment using the LLM API.

    Sends the comment to the configured LLM endpoint for analysis.

    TODO: Implement actual LLM API call when API key is configured.
    Currently returns None to fall back to default behavior.
    """
    if not settings.llm_api_key:
        logger.debug(
            "llm_parse_skipped",
            reason="No LLM API key configured",
        )
        return None

    # TODO: Implement LLM API call
    # The implementation would:
    # 1. Send the comment + diagnostician names to the LLM
    # 2. Parse the JSON response
    # 3. Validate and return the result
    #
    # Example using httpx:
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(
    #         settings.llm_api_url,
    #         headers={"Authorization": f"Bearer {settings.llm_api_key}"},
    #         json={
    #             "model": settings.llm_model,
    #             "messages": [
    #                 {"role": "system", "content": COMMENT_PARSER_SYSTEM_PROMPT},
    #                 {"role": "user", "content": f"Σχόλιο: {comment}\n\nΔιαθέσιμοι ακτινοδιαγνώστες: {', '.join(diagnostician_names)}"},
    #             ],
    #             "response_format": {"type": "json_object"},
    #         },
    #     )
    #     result = response.json()
    #     return json.loads(result["choices"][0]["message"]["content"])

    logger.info("llm_parse_not_implemented", comment=comment[:80])
    return None
