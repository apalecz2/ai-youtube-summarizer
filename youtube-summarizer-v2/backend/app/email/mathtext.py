"""Best-effort LaTeX -> Unicode conversion for email.

Email clients don't run JavaScript, so KaTeX/MathJax (used in the web app) can't
render there. Instead we strip the math delimiters and convert as much of the
LaTeX as we can to Unicode so a summary's equations still read sensibly in an
inbox. Complex expressions degrade to cleaned-up plain text rather than raw
markup. The web app remains the source of truth for perfectly rendered math via
the "Open in app" link.

This runs on the raw Markdown *before* it is handed to the Markdown renderer,
because unconverted `_`/`^`/`\\` would otherwise be mangled into emphasis, etc.
"""
import re

# LaTeX command -> Unicode. Longer names must be tried before their prefixes
# (e.g. \\leftrightarrow before \\left), so we sort by length at match time.
_SYMBOLS = {
    # Greek (lower)
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\iota": "ι", r"\kappa": "κ", r"\lambda": "λ",
    r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ",
    r"\sigma": "σ", r"\tau": "τ", r"\upsilon": "υ", r"\phi": "φ",
    r"\varphi": "φ", r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    # Greek (upper)
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
    r"\Psi": "Ψ", r"\Omega": "Ω",
    # Operators & relations
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\equiv": "≡",
    r"\sim": "∼", r"\propto": "∝", r"\ll": "≪", r"\gg": "≫",
    r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇",
    r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
    r"\forall": "∀", r"\exists": "∃", r"\in": "∈", r"\notin": "∉",
    r"\subset": "⊂", r"\supset": "⊃", r"\subseteq": "⊆", r"\supseteq": "⊇",
    r"\cup": "∪", r"\cap": "∩", r"\emptyset": "∅", r"\varnothing": "∅",
    r"\land": "∧", r"\lor": "∨", r"\neg": "¬",
    r"\leftrightarrow": "↔", r"\rightarrow": "→", r"\leftarrow": "←",
    r"\Rightarrow": "⇒", r"\Leftarrow": "⇐", r"\Leftrightarrow": "⇔",
    r"\to": "→", r"\mapsto": "↦", r"\uparrow": "↑", r"\downarrow": "↓",
    r"\angle": "∠", r"\degree": "°", r"\prime": "′",
    # Common named functions / spacing — drop the backslash, keep the word.
    r"\sqrt": "√", r"\sin": "sin", r"\cos": "cos", r"\tan": "tan",
    r"\log": "log", r"\ln": "ln", r"\exp": "exp", r"\lim": "lim",
    r"\min": "min", r"\max": "max",
    r"\quad": "  ", r"\qquad": "    ", r"\,": " ", r"\;": " ", r"\!": "",
    r"\left": "", r"\right": "", r"\displaystyle": "", r"\text": "",
    r"\%": "%", r"\$": "$", r"\&": "&", r"\#": "#", r"\_": "_",
}

_SUPERSCRIPT = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽",
    ")": "⁾", "n": "ⁿ", "i": "ⁱ", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "x": "ˣ",
}
_SUBSCRIPT = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍",
    ")": "₎", "a": "ₐ", "e": "ₑ", "o": "ₒ", "x": "ₓ", "i": "ᵢ", "j": "ⱼ",
    "n": "ₙ", "m": "ₘ", "t": "ₜ",
}

# A token that, if present between $...$, marks the content as *math* rather than
# a stray currency amount ("$5 and $10"). Inline $-pairs are only treated as math
# when they contain one of these.
_MATH_HINT = re.compile(r"[\\^_{}]|\\[a-zA-Z]+")


def _script(body: str, table: dict[str, str], caret: str) -> str:
    mapped = [table.get(ch) for ch in body]
    if all(m is not None for m in mapped):
        return "".join(mapped)  # type: ignore[arg-type]
    # Not fully mappable — keep it readable with the operator + parens.
    return f"{caret}({body})" if len(body) > 1 else f"{caret}{body}"


def _convert_scripts(s: str) -> str:
    # ^{...} / _{...}
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: _script(m.group(1), _SUPERSCRIPT, "^"), s)
    s = re.sub(r"_\{([^{}]*)\}", lambda m: _script(m.group(1), _SUBSCRIPT, "_"), s)
    # single-char ^x / _x
    s = re.sub(r"\^(\\?[A-Za-z0-9])", lambda m: _script(m.group(1), _SUPERSCRIPT, "^"), s)
    s = re.sub(r"_(\\?[A-Za-z0-9])", lambda m: _script(m.group(1), _SUBSCRIPT, "_"), s)
    return s


def _convert_expr(expr: str) -> str:
    """Convert the inside of a math delimiter to best-effort Unicode."""
    s = expr.strip()
    # \frac{a}{b} -> (a)/(b), a couple of nested levels.
    for _ in range(3):
        new = re.sub(r"\\d?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
        if new == s:
            break
        s = new
    # \sqrt{x} -> √(x)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)
    # Named symbols/commands, longest first so \le doesn't eat \leq.
    for cmd in sorted(_SYMBOLS, key=len, reverse=True):
        if cmd in s:
            s = s.replace(cmd, _SYMBOLS[cmd])
    s = _convert_scripts(s)
    # \text{...} / \mathrm{...} etc: keep the contents, drop the wrapper.
    s = re.sub(r"\\[a-zA-Z]+\s*\{([^{}]*)\}", r"\1", s)
    # Any leftover backslash-commands: drop the backslash, keep the letters.
    s = re.sub(r"\\([a-zA-Z]+)", r"\1", s)
    # Remaining braces are grouping noise now.
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def latex_to_unicode(text: str) -> str:
    """Replace LaTeX math (``$$..$$``, ``$..$``, ``\\[..\\]``, ``\\(..\\)``) with
    best-effort Unicode, stripping the delimiters. Non-math text is untouched."""
    # Display math first: $$...$$, \[...\]
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: _convert_expr(m.group(1)), text, flags=re.DOTALL)
    text = re.sub(r"\\\[(.+?)\\\]", lambda m: _convert_expr(m.group(1)), text, flags=re.DOTALL)
    # Inline: \(...\)
    text = re.sub(r"\\\((.+?)\\\)", lambda m: _convert_expr(m.group(1)), text, flags=re.DOTALL)
    # Inline $...$ — only when it actually looks like math (avoids "$5 ... $10").
    def _inline(m: re.Match[str]) -> str:
        inner = m.group(1)
        return _convert_expr(inner) if _MATH_HINT.search(inner) else m.group(0)
    text = re.sub(r"(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)", _inline, text)
    return text
