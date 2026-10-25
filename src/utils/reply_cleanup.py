import re

from src.utils.logger import logger

_SUPERSCRIPT = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ",
    "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ",
    "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
}
_SUBSCRIPT = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ",
    "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
}

_OPERATORS = {
    "times": "×", "div": "÷", "cdot": "·", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "equiv": "≡", "cong": "≅", "sim": "∼", "parallel": "∥", "perp": "⊥",
    "to": "→", "rightarrow": "→", "Rightarrow": "⇒", "leftarrow": "←", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔", "therefore": "∴", "because": "∵",
    "in": "∈", "notin": "∉", "cup": "∪", "cap": "∩", "subset": "⊂",
}
_ATOMS = {
    "pi": "π", "theta": "θ", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ",
    "lambda": "λ", "mu": "μ", "sigma": "σ", "Sigma": "Σ", "omega": "ω", "phi": "φ",
    "angle": "∠", "triangle": "△", "square": "□", "circ": "°", "degree": "°", "infty": "∞",
    "emptyset": "∅", "cdots": "⋯", "ldots": "…", "dots": "…",
}
_LAYOUT = {
    "left": "", "right": "", "big": "", "Big": "", "displaystyle": "",
    "quad": " ", "qquad": " ", ",": " ", ";": " ", ":": " ", "!": "", " ": " ",
}

_COMMAND = re.compile(r"\\([A-Za-z]+|[,;:! ])( (?=[A-Za-z0-9]))?")
_TEXT_WRAPPER = re.compile(
    r"\\(?:text|mathrm|textbf|mathbf|mathit|operatorname|vec|hat|bar)\s*\{([^{}]*)\}"
)
_OVERLINE_MARK = "\u0305"
_OVERLINE = re.compile(r"\\overline\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_DEGREE = re.compile(r"\^\s*\{?\s*\\circ\s*\}?")
_SUP = re.compile(r"\^\s*(?:\{([^{}]*)\}|(-?[0-9]+|[A-Za-z]))")
_SUB = re.compile(r"_\s*(?:\{([^{}]*)\}|([0-9]+|[A-Za-z]))")
_BARE_SUP = re.compile(r"(?<=[A-Za-z0-9)])\^(?:\{([^{}]*)\}|(-?[0-9]+|[A-Za-z](?![A-Za-z])))")

_MATH_SPAN = re.compile(
    r"\$\$(.+?)\$\$"
    r"|\\\[(.+?)\\\]"
    r"|\\\((.+?)\\\)"
    r"|\$(?=[^\s$])([^$\n]+?)(?<=[^\s$])\$(?!\d)",
    re.S,
)

_KANA = re.compile(r"[\u3040-\u30ff]")
_STRAY_NO = re.compile(r"(?<=[\u4e00-\u9fff0-9A-Za-z)）²³])の(?=[\u4e00-\u9fff0-9A-Za-z(（])")


def _scripted(content: str, table: dict, marker: str) -> str:
    content = content.strip()
    if content and all(ch in table for ch in content):
        return "".join(table[ch] for ch in content)
    return f"{marker}({content})" if len(content) > 1 else f"{marker}{content}"


def _superscript(m: re.Match) -> str:
    return _scripted(m.group(1) if m.group(1) is not None else m.group(2), _SUPERSCRIPT, "^")


def _subscript(m: re.Match) -> str:
    return _scripted(m.group(1) if m.group(1) is not None else m.group(2), _SUBSCRIPT, "_")


def _grouped(content: str) -> str:
    content = content.strip()
    return f"({content})" if re.search(r".[+\-×÷·/= ]", content) else content


def _sqrt(m: re.Match) -> str:
    index, content = (m.group(1) or "").strip(), m.group(2).strip()
    root = {"": "√", "2": "√", "3": "∛", "4": "∜"}.get(index) or _scripted(index, _SUPERSCRIPT, "^") + "√"
    single = re.fullmatch(r"[0-9.]+|[A-Za-zπθ]", content)
    return root + (content if single else f"({content})")


def _overline(m: re.Match) -> str:
    return "".join(ch if ch.isspace() else ch + _OVERLINE_MARK for ch in m.group(1).strip())


def _command(m: re.Match) -> str:
    name, space = m.group(1), m.group(2) or ""
    if name in _ATOMS:
        return _ATOMS[name]
    if name in _OPERATORS:
        return _OPERATORS[name] + space
    if name in _LAYOUT:
        return _LAYOUT[name] + space
    return m.group(0)


def _structures(s: str, sup: re.Pattern, sub: bool) -> str:
    previous = None
    while previous != s:
        previous = s
        s = _OVERLINE.sub(_overline, s)
        s = _TEXT_WRAPPER.sub(lambda m: m.group(1), s)
        s = _SQRT.sub(_sqrt, s)
        s = _FRAC.sub(lambda m: f"{_grouped(m.group(1))}/{_grouped(m.group(2))}", s)
        s = sup.sub(_superscript, s)
        if sub:
            s = _SUB.sub(_subscript, s)
    return s


def _latex_to_text(s: str) -> str:
    s = _DEGREE.sub("°", s)
    s = _COMMAND.sub(_command, s)
    s = _structures(s, _SUP, sub=True)
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def _fix_latex(text: str) -> str:
    text = _MATH_SPAN.sub(lambda m: _latex_to_text(next(g for g in m.groups() if g is not None)), text)
    text = _DEGREE.sub("°", text)
    text = _COMMAND.sub(_command, text)
    return _structures(text, _BARE_SUP, sub=False)


def _fix_japanese(text: str) -> str:
    kana = _KANA.findall(text)
    if not kana or len(kana) > 5:
        return text
    fixed, count = _STRAY_NO.subn("的", text)
    leftover = _KANA.findall(fixed)
    logger.warning(f"老師的回覆夾雜日文假名：換掉 {count} 個「の」，其他假名：{''.join(leftover) or '無'}")
    return fixed


def clean_reply_text(text: str) -> str:
    if not text:
        return text
    return _fix_japanese(_fix_latex(text))
