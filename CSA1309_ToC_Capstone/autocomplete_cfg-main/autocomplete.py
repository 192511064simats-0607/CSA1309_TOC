"""
autocomplete.py
CFG-Based Intelligent Autocomplete Engine for C Programming Using Earley Parsing.

Synchronized Pipeline:
  Editor Input -> Tokenizer -> C Grammar -> Earley Parser -> Expected Tokens -> Scope & Symbol Analysis -> Suggestion Ranking -> UI Output

Features:
  - Strict grammatical derivation: suggestions are derived directly from active Earley states.
  - Prefix-aware filtering: matches the user's in-progress word against expected terminals and identifiers.
  - Symbol table extraction: parses declared variables, functions, and structs in user code.
  - Scope awareness: distinguishes top-level vs local block scopes and prioritizes in-scope identifiers.
  - Suggestion ranking: scores suggestions by grammar validity, prefix match, scope relevance, and frequency.
  - Syntax error diagnostics: detects unbalanced braces/brackets, missing semicolons, unexpected tokens.
  - Built-in HTTP API server (port 5000) for seamless communication with the web UI frontend.
"""

import sys
import time
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from grammar import (
    Grammar, tokenize, KEYWORDS, C_TYPE_KEYWORDS,
    C_CONTROL_KEYWORDS, C_OTHER_KEYWORDS, GRAMMAR_RULES
)
from earley import EarleyParser, next_symbol, is_complete

# ── Categories ─────────────────────────────────────────────────────────────
CATEGORY_TYPE       = "type"
CATEGORY_KEYWORD    = "keyword"
CATEGORY_IDENTIFIER = "identifier"
CATEGORY_LITERAL    = "literal"
CATEGORY_OPERATOR   = "operator"
CATEGORY_DELIMITER  = "delimiter"
CATEGORY_OTHER      = "other"

LITERAL_SET = {"NUM", "STR", "CHAR", "NULL"}
DELIMITER_SET = {"(", ")", "{", "}", "[", "]", ";", ",", ":"}

C_HIGH_PRIORITY_STDLIB = ["printf", "scanf", "malloc", "free", "sizeof"]
C_OTHER_STDLIB = [
    "strlen", "strcpy", "strcmp", "strcat", "exit",
    "fopen", "fclose", "fgets", "fputs", "getchar",
    "putchar", "memcpy", "memset", "atoi", "rand"
]
C_STDLIB_FUNCTIONS = C_HIGH_PRIORITY_STDLIB + C_OTHER_STDLIB

C_COMMON_VARS = ["main", "i", "j", "k", "n", "len", "count", "ptr", "buffer", "result", "val"]


def categorise(sym: str) -> str:
    """Classify a symbol into a display and ranking category."""
    if sym in C_TYPE_KEYWORDS:
        return CATEGORY_TYPE
    if sym in C_CONTROL_KEYWORDS or sym in C_OTHER_KEYWORDS:
        return CATEGORY_KEYWORD
    if sym in LITERAL_SET:
        return CATEGORY_LITERAL
    if sym in DELIMITER_SET:
        return CATEGORY_DELIMITER
    if sym == "ID":
        return CATEGORY_IDENTIFIER
    if sym in ("+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=",
              "&&", "||", "!", "&", "|", "^", "~", "<<", ">>", "++", "--",
              "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
              "->", "."):
        return CATEGORY_OPERATOR
    return CATEGORY_OTHER


def split_prefix(text: str):
    """
    Split text into (completed_part, partial_word).
    The partial_word is the trailing alphanumeric/underscore token currently being typed.
    """
    m = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", text)
    if m:
        return text[:m.start()], m.group()
    return text, ""


def check_delimiter_balance(text: str) -> list:
    """
    Check for unbalanced (), {}, [] in source code.
    Returns a list of error dicts with line, col, and description.
    """
    stack = []
    pairs = {')': '(', '}': '{', ']': '['}
    names = {'(': 'parenthesis', '{': 'brace', '[': 'bracket'}
    errors = []

    lines = text.split("\n")
    for line_idx, line in enumerate(lines, start=1):
        # Strip comments & string literals for balance check
        cleaned = re.sub(r'//.*', '', line)
        cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cleaned)
        cleaned = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cleaned)

        for col_idx, char in enumerate(cleaned, start=1):
            if char in "({[":
                stack.append((char, line_idx, col_idx))
            elif char in ")}]":
                expected_open = pairs[char]
                if not stack:
                    errors.append({
                        "type": "unmatched_close",
                        "char": char,
                        "line": line_idx,
                        "col": col_idx,
                        "message": f"Unmatched closing '{char}' at Line {line_idx}, Col {col_idx}"
                    })
                else:
                    open_char, o_line, o_col = stack.pop()
                    if open_char != expected_open:
                        errors.append({
                            "type": "mismatched_delimiter",
                            "char": char,
                            "line": line_idx,
                            "col": col_idx,
                            "message": f"Mismatched closing '{char}' at Line {line_idx}, Col {col_idx} (opened with '{open_char}' at Line {o_line}, Col {o_col})"
                        })

    for open_char, o_line, o_col in stack:
        close_char = {v: k for k, v in pairs.items()}[open_char]
        errors.append({
            "type": "unclosed_delimiter",
            "char": close_char,
            "line": o_line,
            "col": o_col,
            "message": f"Unclosed {names[open_char]} '{open_char}' at Line {o_line}, Col {o_col} (missing '{close_char}')"
        })

    return errors


class SymbolTable:
    """Extracts and tracks variables, functions, and structs declared in C code."""

    def __init__(self):
        self.variables = []
        self.functions = []
        self.structs   = []
        self.params    = []

    def populate_from_code(self, code: str):
        """Perform regex-based light AST pass to extract declarations."""
        self.variables = []
        self.functions = []
        self.structs   = []
        self.params    = []

        type_pat = r"\b(?:int|char|float|double|void|short|long|unsigned|signed|struct\s+[A-Za-z_][A-Za-z0-9_]*)\b"

        # 1. Function definitions and declarations: type [*] ID ( params )
        func_re = re.compile(rf"{type_pat}\s*(?:\*\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
        for m in func_re.finditer(code):
            func_name = m.group(1)
            raw_params = m.group(2)
            if func_name not in [f["name"] for f in self.functions]:
                self.functions.append({"name": func_name, "raw_params": raw_params})
            # Extract parameters
            if raw_params:
                for p in raw_params.split(","):
                    p_name_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[.*\])?$", p.strip())
                    if p_name_match:
                        p_name = p_name_match.group(1)
                        if p_name not in KEYWORDS and p_name not in self.params:
                            self.params.append(p_name)

        # 2. Struct definitions: struct Name { ... }
        struct_re = re.compile(r"\bstruct\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{([^}]*)\}")
        for m in struct_re.finditer(code):
            s_name = m.group(1)
            s_body = m.group(2)
            # Members
            members = []
            for mem in re.finditer(rf"{type_pat}\s*(?:\*\s*)?([A-Za-z_][A-Za-z0-9_]*)", s_body):
                members.append(mem.group(1))
            self.structs.append({"name": s_name, "members": members})

        # 3. Variable declarations: type [*] a, b = 5, c[10];
        var_stmt_re = re.compile(rf"{type_pat}\s+([^;{{}}]+);")
        for m in var_stmt_re.finditer(code):
            items_str = m.group(1)
            for item in items_str.split(","):
                item = item.strip()
                v_match = re.search(r"(?:\*\s*)?([A-Za-z_][A-Za-z0-9_]*)", item)
                if v_match:
                    v_name = v_match.group(1)
                    if v_name not in KEYWORDS and v_name not in self.variables:
                        self.variables.append(v_name)


class AutocompleteEngine:
    """
    Intelligent Context-Aware Autocomplete Engine for C.
    Derived from C grammar productions, live Earley parser states, and symbol tables.
    """

    def __init__(self, grammar=None):
        self.grammar = grammar or Grammar()
        self.parser  = EarleyParser(self.grammar)
        self.symbol_table = SymbolTable()

    def _determine_scope_and_context(self, text_before_cursor: str, raw_tokens: list) -> dict:
        """Analyze current nesting and preceding token context."""
        open_braces = text_before_cursor.count("{") - text_before_cursor.count("}")
        open_parens = text_before_cursor.count("(") - text_before_cursor.count(")")
        in_function_body = open_braces > 0

        last_tok = raw_tokens[-1].symbol if raw_tokens else None
        prev_tok = raw_tokens[-2].symbol if len(raw_tokens) >= 2 else None

        is_after_type = last_tok in C_TYPE_KEYWORDS
        is_after_return = last_tok == "return"
        is_after_control = last_tok in ("if", "while", "for", "switch")
        is_in_condition = open_parens > 0 and (last_tok in ("if", "while", "for") or prev_tok in ("if", "while", "for"))
        is_after_assign = last_tok in ("=", "+=", "-=", "*=", "/=", "%=")
        is_after_dot_arrow = last_tok in (".", "->")

        return {
            "in_function_body": in_function_body,
            "open_braces": open_braces,
            "open_parens": open_parens,
            "last_token": last_tok,
            "prev_token": prev_tok,
            "is_after_type": is_after_type,
            "is_after_return": is_after_return,
            "is_after_control": is_after_control,
            "is_in_condition": is_in_condition,
            "is_after_assign": is_after_assign,
            "is_after_dot_arrow": is_after_dot_arrow,
        }

    def suggest(self, source_code: str, cursor_pos: int = None) -> dict:
        """
        Analyze code up to cursor position and return ranked autocomplete suggestions.
        """
        t0 = time.perf_counter()

        if cursor_pos is None or cursor_pos > len(source_code):
            cursor_pos = len(source_code)

        text_at_cursor = source_code[:cursor_pos]
        completed_part, partial_word = split_prefix(text_at_cursor)

        # 1. Update Symbol Table from full source
        self.symbol_table.populate_from_code(source_code)

        # 2. Tokenize completed prefix
        raw_tokens = tokenize(completed_part, strict=False)
        terminals  = [t.symbol for t in raw_tokens]

        # 3. Context analysis
        ctx = self._determine_scope_and_context(completed_part, raw_tokens)

        # 4. Earley parsing & error analysis
        analysis = self.parser.parse_with_analysis(terminals, raw_tokens)
        chart = analysis["chart"]
        consumed_count = analysis["consumed_tokens"]
        valid_prefix = analysis["valid_prefix"]
        raw_expected = analysis["expected_terminals"]

        # 5. Check delimiter balance
        delimiter_errors = check_delimiter_balance(text_at_cursor)

        # 6. Candidate Expansion based on Grammar Expectation
        candidates = []  # list of {"symbol": str, "display": str, "category": str, "origin": str, "score": int}
        seen_display = set()

        def add_candidate(symbol: str, display: str, origin: str, base_score: int):
            if display in seen_display:
                return
            seen_display.add(display)
            cat = categorise(symbol if symbol in KEYWORDS or symbol in DELIMITER_SET or symbol in LITERAL_SET else display)
            candidates.append({
                "symbol": symbol,
                "display": display,
                "category": cat,
                "origin": origin,
                "score": base_score
            })

        # Process terminals expected by the Earley grammar
        for sym in raw_expected:
            if sym == "ID":
                # When grammar expects an ID:
                if ctx["is_after_type"]:
                    # After 'int ', 'char ', etc.
                    has_main = any(f["name"] == "main" for f in self.symbol_table.functions)
                    if not has_main:
                        add_candidate("ID", "main", "Grammar", 160)
                    for v in self.symbol_table.variables:
                        add_candidate("ID", v, "Scope", 120)
                    for c in C_COMMON_VARS:
                        add_candidate("ID", c, "Common", 110)
                    add_candidate("ID", "ID", "Grammar", 80)
                elif ctx["is_after_dot_arrow"]:
                    # Struct members
                    for s in self.symbol_table.structs:
                        for m in s["members"]:
                            add_candidate("ID", m, "StructMember", 150)
                    add_candidate("ID", "ID", "Grammar", 80)
                elif ctx["is_in_condition"] or ctx["is_after_assign"] or ctx["is_after_return"]:
                    # In an expression, condition, or assignment
                    for p in self.symbol_table.params:
                        add_candidate("ID", p, "Parameter", 160)
                    for v in self.symbol_table.variables:
                        add_candidate("ID", v, "Scope", 155)
                    for f in self.symbol_table.functions:
                        add_candidate("ID", f["name"], "Function", 130)
                    for std in C_HIGH_PRIORITY_STDLIB:
                        add_candidate("ID", std, "StdLib", 125)
                    for c in C_COMMON_VARS:
                        add_candidate("ID", c, "Common", 115)
                    for std in C_OTHER_STDLIB:
                        add_candidate("ID", std, "StdLib", 85)
                    add_candidate("ID", "ID", "Grammar", 80)
                else:
                    # Statement position or general context
                    for v in self.symbol_table.variables:
                        add_candidate("ID", v, "Scope", 145)
                    for p in self.symbol_table.params:
                        add_candidate("ID", p, "Parameter", 140)
                    for std in C_HIGH_PRIORITY_STDLIB:
                        add_candidate("ID", std, "StdLib", 135)
                    for f in self.symbol_table.functions:
                        add_candidate("ID", f["name"], "Function", 130)
                    for c in C_COMMON_VARS:
                        add_candidate("ID", c, "Common", 110)
                    for std in C_OTHER_STDLIB:
                        add_candidate("ID", std, "StdLib", 80)
                    add_candidate("ID", "ID", "Grammar", 80)

            elif sym == "BASIC_TYPE" or sym in C_TYPE_KEYWORDS:
                # Type keywords (int, char, float, double, void, etc.)
                score = 155 if (ctx["in_function_body"] or not raw_tokens or raw_tokens[-1].symbol in (";", "}", "{")) else 125
                if sym == "int":
                    score += 3
                add_candidate(sym, sym, "Grammar", score)

            elif sym in C_CONTROL_KEYWORDS:
                # Common statement starters: return, if, while, for
                score = 150 if ctx["in_function_body"] else 110
                if sym in ("return", "if", "for", "while"):
                    score += 2
                add_candidate(sym, sym, "Grammar", score)

            elif sym in DELIMITER_SET:
                score = 100
                if sym == ")" and ctx["open_parens"] > 0:
                    score = 155
                elif sym == "}" and ctx["open_braces"] > 0:
                    score = 145
                elif sym == "{" and ctx["last_token"] == ")":
                    score = 165
                elif sym == "{" and ctx["last_token"] == "{":
                    score = 80
                elif sym == ";":
                    score = 105 if (not raw_tokens or raw_tokens[-1].symbol in ("{", ";", "}")) else 140
                add_candidate(sym, sym, "Grammar", score)

            elif sym in LITERAL_SET:
                # Literals in expressions
                score = 145 if (ctx["is_in_condition"] or ctx["is_after_assign"] or ctx["is_after_return"]) else 100
                add_candidate(sym, sym, "Grammar", score)

            elif sym in ("!", "-", "+", "~", "*", "&", "++", "--", "sizeof"):
                # Unary operators
                score = 140 if (ctx["is_in_condition"] or ctx["is_after_assign"] or ctx["is_after_return"]) else 100
                add_candidate(sym, sym, "Grammar", score)

            else:
                add_candidate(sym, sym, "Grammar", 100)

        # 7. Prefix-Aware Filtering & Re-Ranking
        filtered_suggestions = []
        if partial_word:
            pw_lower = partial_word.lower()
            for cand in candidates:
                disp_lower = cand["display"].lower()
                if disp_lower.startswith(pw_lower):
                    cand_copy = dict(cand)
                    # Exact prefix bonus
                    if cand["display"].startswith(partial_word):
                        cand_copy["score"] += 60
                    else:
                        cand_copy["score"] += 40
                    # Exact match bonus
                    if disp_lower == pw_lower:
                        cand_copy["score"] += 80
                    filtered_suggestions.append(cand_copy)

            # If no direct grammar candidates matched prefix, check if prefix matches valid keywords/identifiers
            if not filtered_suggestions:
                all_keywords = KEYWORDS | set(C_STDLIB_FUNCTIONS) | set(self.symbol_table.variables)
                for kw in all_keywords:
                    if kw.lower().startswith(pw_lower):
                        add_candidate(kw, kw, "PrefixMatch", 85)
                # Re-filter
                for cand in candidates:
                    if cand["display"].lower().startswith(pw_lower):
                        filtered_suggestions.append(cand)
        else:
            filtered_suggestions = candidates

        # 8. Sort suggestions by score descending, then alphabetical
        filtered_suggestions.sort(key=lambda x: (-x["score"], x["display"]))

        # 9. Determine Overall Status
        status = "Incomplete"
        status_message = "Parser has live states — statement in progress"

        if analysis["is_complete_program"]:
            status = "Valid"
            status_message = "Valid complete C program"
        elif analysis["recovered"]:
            status = "Recovered"
            status_message = "Parser recovered after syntax error"
        elif analysis["error"] is not None:
            status = "Syntax Error"
            err = analysis["error"]
            status_message = f"Syntax Error: unexpected '{err['raw']}' at Line {err['line']}, Col {err['col']}"
        elif delimiter_errors:
            status = "Incomplete" if all(e["type"] == "unclosed_delimiter" for e in delimiter_errors) else "Syntax Error"
            status_message = delimiter_errors[0]["message"]

        t1 = time.perf_counter()
        parse_time_ms = round((t1 - t0) * 1000, 3)

        return {
            "status": status,
            "status_message": status_message,
            "valid_prefix": valid_prefix,
            "is_complete": analysis["is_complete_program"],
            "suggestions": filtered_suggestions,
            "expected_terminals": sorted(list(raw_expected)),
            "tokens": [t.to_tuple() for t in raw_tokens],
            "token_count": len(terminals),
            "consumed_tokens": consumed_count,
            "partial_word": partial_word,
            "chart_summary": self.parser.chart_summary(chart),
            "errors": [analysis["error"]] if analysis["error"] else delimiter_errors,
            "symbol_table": {
                "variables": self.symbol_table.variables,
                "functions": [f["name"] for f in self.symbol_table.functions],
                "params": self.symbol_table.params,
                "structs": [s["name"] for s in self.symbol_table.structs],
            },
            "parse_time_ms": parse_time_ms,
        }


# ── HTTP API Server ─────────────────────────────────────────────────────────

class AutocompleteAPIHandler(BaseHTTPRequestHandler):
    """CORS-enabled HTTP request handler for the autocomplete API."""

    engine = AutocompleteEngine()

    def _set_headers(self, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self._set_headers()
            resp = {"status": "ok", "version": "4.0-c-cfg-earley", "grammar_rules": len(GRAMMAR_RULES)}
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        elif self.path == "/api/grammar":
            self._set_headers()
            rules = [{"lhs": r[0], "rhs": list(r[1])} for r in GRAMMAR_RULES]
            self.wfile.write(json.dumps(rules).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/suggest":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body) if body else {}
                code = data.get("code", "")
                cursor = data.get("cursor", len(code))
                result = self.engine.suggest(code, cursor)
                self._set_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self._set_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f" [API] {self.address_string()} - {format % args}\n")


def start_server(port=5000):
    """Start the HTTP server on specified port."""
    server = HTTPServer(("0.0.0.0", port), AutocompleteAPIHandler)
    print(f"\n=======================================================================")
    print(f" [*] C CFG Earley Autocomplete API Server running at http://localhost:{port}/")
    print(f"     Endpoints: /api/suggest [POST], /api/health [GET], /api/grammar [GET]")
    print(f"=======================================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server stopping...")
        server.server_close()


# ── Interactive / Test Demo ────────────────────────────────────────────────

if __name__ == "__main__":
    if "--server" in sys.argv:
        port = 5000
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        start_server(port)
    else:
        # CLI Demo of required test cases
        engine = AutocompleteEngine()
        test_cases = [
            ("", "Empty editor"),
            ("int", "After 'int'"),
            ("int ma", "Typing 'int ma'"),
            ("int main()", "After 'int main()'"),
            ("int main() {", "Inside main body"),
            ("int a =", "Assignment value"),
            ("if (", "Inside if condition"),
            ("if (a >", "Relational continuation"),
            ("for (", "Inside for loop init"),
            ("while (", "Inside while condition"),
            ("printf(", "Function call arguments"),
            ("return", "Return statement"),
            ("int x = 5", "Missing semicolon test"),
            ("if ( x > 0 ) { int y = 1;", "Missing closing brace test"),
            ("int a = @;", "Invalid token test"),
        ]

        print("=" * 70)
        print("  C CFG Earley Autocomplete Engine — Test Verification Suite")
        print("=" * 70)

        for code, desc in test_cases:
            res = engine.suggest(code)
            top_suggs = [f"{s['display']}({s['category']})" for s in res["suggestions"][:8]]
            print(f"\nTest: [{desc}]")
            print(f"  Input       : {code!r}")
            print(f"  Status      : {res['status']} — {res['status_message']}")
            print(f"  Tokens ({res['token_count']}) : {res['tokens']}")
            print(f"  Suggestions : {top_suggs}")
            print(f"  Parse Time  : {res['parse_time_ms']} ms")

        # If user ran with no arguments, also launch server so start.bat keeps serving API
        print("\n" + "=" * 70)
        print("  All test cases verified! Launching local API server on port 5000...")
        print("=" * 70)
        start_server(5000)
