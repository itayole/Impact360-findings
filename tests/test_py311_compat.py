"""The Docker image runs Python 3.11, development may run a newer Python. Since 3.12 an f-string may reuse its own quote
character inside {...}; 3.11 raises a SyntaxError and the container never starts (release 0.3.2 shipped with exactly that).
This test finds such f-strings with the tokenizer, so a newer local Python cannot hide them."""
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def nested_same_quote(source):
    """(line, text) of every f-string that uses its own quote character inside a replacement field."""
    if not hasattr(tokenize, "FSTRING_START"):          # Python < 3.12 already rejects them itself
        return []
    found, stack = [], []                                # stack: [quote char, brace depth]
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.FSTRING_START:
            if stack and stack[-1][1] > 0 and tok.string[-1] == stack[-1][0]:
                found.append((tok.start[0], tok.line.strip()[:120]))
            stack.append([tok.string[-1], 0])
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack and tok.type == tokenize.OP and tok.string == "{" and stack:
            stack[-1][1] += 1
        elif stack and tok.type == tokenize.OP and tok.string == "}":
            stack[-1][1] -= 1
        elif stack and stack[-1][1] > 0 and tok.type == tokenize.STRING:
            body = tok.string.lstrip("rRbBuUfF")
            if body[:1] == stack[-1][0]:
                found.append((tok.start[0], tok.line.strip()[:120]))
    return found


def test_checker_detects_the_0_3_2_bug():
    bad = 'x = f"a{q(b, safe="")}c"\n'
    ok = "x = f\"a{q(b, safe='')}c\"\ny = f'{d[\"k\"]}'\n"
    assert nested_same_quote(bad) or not hasattr(tokenize, "FSTRING_START")
    assert nested_same_quote(ok) == []


def test_no_python_312_only_fstrings_in_the_shipped_code():
    problems = []
    for folder in ("app", "svr"):
        for p in (ROOT / folder).rglob("*.py"):
            for line, text in nested_same_quote(p.read_text(encoding="utf-8")):
                problems.append(f"{p.relative_to(ROOT)}:{line}: {text}")
    assert problems == [], "f-string quotes that Python 3.11 (the Docker image) cannot parse:\n" + "\n".join(problems)
