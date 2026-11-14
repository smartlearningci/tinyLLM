#!/usr/bin/env python3
"""Reparacoes locais conservadoras; nunca altera a fonte nem inventa citacoes."""
import copy
import re
import unicodedata

import distill


def tokens(text):
    """Sequencia de palavras com pontuacao ignorada, preservando acentos."""
    return re.findall(r"[^\\W_]+", unicodedata.normalize("NFKC", text).casefold(), re.UNICODE)


def repair_quote(quote, source):
    """Devolve trecho LITERAL da fonte se a sequencia de palavras e unica.

    Nao corrige sinonimos, palavras em falta, acrescimos ou mudancas semanticas.
    """
    words = tokens(quote)
    if len(words) < 3 or len(quote.strip()) < 12:
        return None
    # Percorre palavras da fonte guardando limites; mantem pontuacao real da fonte.
    matches = list(re.finditer(r"[^\\W_]+", source, re.UNICODE))
    folded = [unicodedata.normalize("NFKC", m.group()).casefold() for m in matches]
    hits = []
    n = len(words)
    for i in range(len(folded) - n + 1):
        if folded[i:i+n] == words:
            hits.append(source[matches[i].start():matches[i+n-1].end()])
            if len(hits) > 1:
                return None
    return hits[0] if len(hits) == 1 else None


def repair_response(raw, request):
    """Corrige apenas aspas/pontuacao de citacoes inequivocas; valida tudo no fim."""
    candidate = copy.deepcopy(raw)
    changed = []
    sources = distill.sources_for(request)
    for example in candidate.get("examples", []):
        for evidence in example.get("evidence", []):
            source = sources.get(evidence.get("source_id"))
            quote = evidence.get("quote")
            if not source or not isinstance(quote, str):
                continue
            if distill.normalize(quote) in distill.normalize(source):
                continue
            literal = repair_quote(quote, source)
            if literal is None:
                continue
            evidence["quote"] = literal
            changed.append({"slot": example["slot"],
                            "source_id": evidence["source_id"],
                            "original": quote, "literal": literal})
    if not changed:
        return None, []
    try:
        distill.validate_response(candidate, request)
    except ValueError:
        return None, []
    return candidate, changed
