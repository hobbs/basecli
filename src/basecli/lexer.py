"""Tokenizer for the Bases expression grammar.

Handles the regexp/division ambiguity the same way JS lexers do: a ``/`` starts
a regexp literal unless the previous significant token is a *value* (identifier,
number, string, regexp, ``)`` or ``]``), in which case it is the division
operator.
"""

from __future__ import annotations

from typing import List, NamedTuple

from .errors import ParseError


class Token(NamedTuple):
    type: str
    value: object
    pos: int


# Multi-char operators, longest first.
_OPERATORS = [
    "&&", "||", "==", "!=", ">=", "<=",
    "+", "-", "*", "/", "%",
    ">", "<", "!", "(", ")", "[", "]", "{", "}", ".", ",", ":", "|", "&",
]

_VALUE_TOKENS = {"NUMBER", "STRING", "IDENT", "REGEXP", "RPAREN", "RBRACKET"}

_PUNCT_TYPE = {
    "(": "LPAREN", ")": "RPAREN", "[": "LBRACKET", "]": "RBRACKET",
    "{": "LBRACE", "}": "RBRACE", ".": "DOT", ",": "COMMA", ":": "COLON",
}


def tokenize(src: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(src)
    prev_type = None

    def push(t: str, v, p):
        nonlocal prev_type
        tokens.append(Token(t, v, p))
        prev_type = t

    while i < n:
        c = src[i]

        if c in " \t\r\n":
            i += 1
            continue

        # Strings
        if c == '"' or c == "'":
            value, i = _read_string(src, i, c)
            push("STRING", value, i)
            continue

        # Numbers
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            value, i = _read_number(src, i)
            push("NUMBER", value, i)
            continue

        # Identifiers / keywords
        if c.isalpha() or c == "_" or c == "$":
            start = i
            i += 1
            while i < n and (src[i].isalnum() or src[i] in "_$"):
                i += 1
            word = src[start:i]
            if word == "true":
                push("BOOL", True, start)
            elif word == "false":
                push("BOOL", False, start)
            elif word in ("null", "none"):
                push("NULL", None, start)
            else:
                push("IDENT", word, start)
            continue

        # Regexp vs division
        if c == "/" and prev_type not in _VALUE_TOKENS:
            value, i = _read_regexp(src, i)
            push("REGEXP", value, i)
            continue

        # Operators / punctuation
        matched = False
        for op in _OPERATORS:
            if src.startswith(op, i):
                ttype = _PUNCT_TYPE.get(op, "OP")
                push(ttype, op, i)
                i += len(op)
                matched = True
                break
        if matched:
            continue

        raise ParseError(f"Unexpected character {c!r} at position {i}", {"pos": i, "source": src})

    tokens.append(Token("EOF", None, n))
    return tokens


def _read_string(src: str, i: int, quote: str):
    n = len(src)
    i += 1  # skip opening quote
    out = []
    while i < n:
        c = src[i]
        if c == "\\" and i + 1 < n:
            nxt = src[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                        '"': '"', "'": "'", "/": "/"}.get(nxt, nxt))
            i += 2
            continue
        if c == quote:
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ParseError("Unterminated string literal", {"pos": i})


def _read_number(src: str, i: int):
    n = len(src)
    start = i
    seen_dot = False
    seen_exp = False
    while i < n:
        c = src[i]
        if c.isdigit():
            i += 1
        elif c == "." and not seen_dot and not seen_exp and i + 1 < n and src[i + 1].isdigit():
            # A '.' is a decimal point only if a digit follows; otherwise it is
            # member access on a number literal, e.g. `1.isTruthy()`.
            seen_dot = True
            i += 1
        elif c in "eE" and not seen_exp:
            seen_exp = True
            i += 1
            if i < n and src[i] in "+-":
                i += 1
        else:
            break
    text = src[start:i]
    if seen_dot or seen_exp:
        return float(text), i
    return int(text), i


def _read_regexp(src: str, i: int):
    n = len(src)
    i += 1  # skip opening /
    pat = []
    while i < n:
        c = src[i]
        if c == "\\" and i + 1 < n:
            pat.append(c)
            pat.append(src[i + 1])
            i += 2
            continue
        if c == "/":
            i += 1
            flags = []
            while i < n and src[i].isalpha():
                flags.append(src[i])
                i += 1
            return ("".join(pat), "".join(flags)), i
        pat.append(c)
        i += 1
    raise ParseError("Unterminated regular expression literal", {"pos": i})
