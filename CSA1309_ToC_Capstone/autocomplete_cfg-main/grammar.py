"""
grammar.py
Context-Free Grammar (CFG) and Tokenizer for the C Programming Language.
Designed for Earley parsing and context-aware intelligent autocompletion.

Supported C constructs:
  - Primitive and compound data types (int, char, float, double, void, short, long, unsigned, signed, struct)
  - Variable declarations, pointers, arrays, and initializations
  - Function declarations (prototypes) and definitions with parameters
  - Control flow: if / else, while, do-while, for loops, switch / case / default
  - Jump statements: return, break, continue
  - Arithmetic, logical, bitwise, relational, and assignment operators
  - Function calls, pointer dereference (*ptr), address-of (&var), struct member access (. and ->)
  - Preprocessor/header awareness and C string/char literals
"""

import re
from collections import defaultdict

# ── C Grammar Productions ──────────────────────────────────────────────────
# Convention: UPPERCASE identifiers are non-terminals; lowercase and symbols are terminals.
GRAMMAR_RULES = [
    # Top-level Program / Declarations / Statements
    ("PROGRAM", ("DECL_LIST",)),
    ("DECL_LIST", ("DECL_ITEM", "DECL_LIST")),
    ("DECL_LIST", ("DECL_ITEM",)),
    ("DECL_ITEM", ("FUNC_DEF",)),
    ("DECL_ITEM", ("FUNC_DECL",)),
    ("DECL_ITEM", ("STRUCT_DECL",)),
    ("DECL_ITEM", ("STMT",)),

    # Types
    ("TYPE", ("BASIC_TYPE",)),
    ("TYPE", ("STRUCT_TYPE",)),
    ("BASIC_TYPE", ("int",)),
    ("BASIC_TYPE", ("char",)),
    ("BASIC_TYPE", ("float",)),
    ("BASIC_TYPE", ("double",)),
    ("BASIC_TYPE", ("void",)),
    ("BASIC_TYPE", ("short",)),
    ("BASIC_TYPE", ("long",)),
    ("BASIC_TYPE", ("unsigned",)),
    ("BASIC_TYPE", ("signed",)),
    ("STRUCT_TYPE", ("struct", "ID")),

    # Variable Declarations
    ("VAR_DECL", ("TYPE", "VAR_INIT_LIST", ";")),
    ("VAR_INIT_LIST", ("VAR_INIT_LIST", ",", "VAR_ITEM")),
    ("VAR_INIT_LIST", ("VAR_ITEM",)),
    ("VAR_ITEM", ("ID",)),
    ("VAR_ITEM", ("*", "ID")),
    ("VAR_ITEM", ("ID", "=", "EXPR")),
    ("VAR_ITEM", ("*", "ID", "=", "EXPR")),
    ("VAR_ITEM", ("ID", "[", "EXPR", "]")),
    ("VAR_ITEM", ("ID", "[", "]")),
    ("VAR_ITEM", ("ID", "[", "EXPR", "]", "=", "{", "ARGLIST", "}")),
    ("VAR_ITEM", ("ID", "[", "]", "=", "STR")),

    # Struct Declarations
    ("STRUCT_DECL", ("struct", "ID", "{", "STRUCT_MEMBERS", "}", ";")),
    ("STRUCT_DECL", ("struct", "ID", "{", "STRUCT_MEMBERS", "}", "VAR_INIT_LIST", ";")),
    ("STRUCT_MEMBERS", ("STRUCT_MEMBER", "STRUCT_MEMBERS")),
    ("STRUCT_MEMBERS", ("STRUCT_MEMBER",)),
    ("STRUCT_MEMBER", ("TYPE", "VAR_INIT_LIST", ";")),

    # Function Declarations & Definitions
    ("FUNC_DECL", ("TYPE", "ID", "(", ")", ";")),
    ("FUNC_DECL", ("TYPE", "ID", "(", "PARAMS", ")", ";")),
    ("FUNC_DECL", ("TYPE", "*", "ID", "(", ")", ";")),
    ("FUNC_DECL", ("TYPE", "*", "ID", "(", "PARAMS", ")", ";")),
    ("FUNC_DEF", ("TYPE", "ID", "(", ")", "BLOCK")),
    ("FUNC_DEF", ("TYPE", "ID", "(", "PARAMS", ")", "BLOCK")),
    ("FUNC_DEF", ("TYPE", "*", "ID", "(", ")", "BLOCK")),
    ("FUNC_DEF", ("TYPE", "*", "ID", "(", "PARAMS", ")", "BLOCK")),
    ("PARAMS", ("PARAMS", ",", "PARAM")),
    ("PARAMS", ("PARAM",)),
    ("PARAM", ("TYPE", "ID")),
    ("PARAM", ("TYPE", "*", "ID")),
    ("PARAM", ("TYPE",)),
    ("PARAM", ("TYPE", "ID", "[", "]")),
    ("PARAM", ("TYPE", "ID", "[", "EXPR", "]")),

    # Statements
    ("STMT", ("VAR_DECL",)),
    ("STMT", ("EXPR_STMT",)),
    ("STMT", ("IF",)),
    ("STMT", ("WHILE",)),
    ("STMT", ("DO_WHILE",)),
    ("STMT", ("FOR",)),
    ("STMT", ("SWITCH",)),
    ("STMT", ("RETURN",)),
    ("STMT", ("BREAK",)),
    ("STMT", ("CONTINUE",)),
    ("STMT", ("BLOCK",)),

    ("BLOCK", ("{", "STMTS", "}")),
    ("BLOCK", ("{", "}")),
    ("STMTS", ("STMT", "STMTS")),
    ("STMTS", ("STMT",)),

    ("EXPR_STMT", ("EXPR", ";")),
    ("EXPR_STMT", (";",)),

    ("RETURN", ("return", "EXPR", ";")),
    ("RETURN", ("return", ";")),
    ("BREAK", ("break", ";")),
    ("CONTINUE", ("continue", ";")),

    # Control Flow
    ("IF", ("if", "(", "COND", ")", "STMT")),
    ("IF", ("if", "(", "COND", ")", "STMT", "else", "STMT")),

    ("WHILE", ("while", "(", "COND", ")", "STMT")),
    ("DO_WHILE", ("do", "STMT", "while", "(", "COND", ")", ";")),

    # For loops (standard variants)
    ("FOR", ("for", "(", "FOR_INIT", ";", "FOR_COND", ";", "FOR_UPDATE", ")", "STMT")),
    ("FOR", ("for", "(", ";", "FOR_COND", ";", "FOR_UPDATE", ")", "STMT")),
    ("FOR", ("for", "(", "FOR_INIT", ";", ";", "FOR_UPDATE", ")", "STMT")),
    ("FOR", ("for", "(", "FOR_INIT", ";", "FOR_COND", ";", ")", "STMT")),
    ("FOR", ("for", "(", ";", ";", ")", "STMT")),

    ("FOR_INIT", ("TYPE", "VAR_INIT_LIST")),
    ("FOR_INIT", ("EXPR",)),
    ("FOR_COND", ("COND",)),
    ("FOR_UPDATE", ("EXPR",)),

    # Switch / Case
    ("SWITCH", ("switch", "(", "EXPR", ")", "{", "CASES", "}")),
    ("SWITCH", ("switch", "(", "EXPR", ")", "{", "}")),
    ("CASES", ("CASE_STMT", "CASES")),
    ("CASES", ("CASE_STMT",)),
    ("CASE_STMT", ("case", "EXPR", ":", "STMTS")),
    ("CASE_STMT", ("case", "EXPR", ":")),
    ("CASE_STMT", ("default", ":", "STMTS")),
    ("CASE_STMT", ("default", ":")),

    # Condition & Expressions
    ("COND", ("EXPR",)),

    ("EXPR", ("ASSIGN_EXPR",)),
    ("ASSIGN_EXPR", ("LVALUE", "ASSIGN_OP", "ASSIGN_EXPR")),
    ("ASSIGN_EXPR", ("BIN_EXPR",)),

    ("ASSIGN_OP", ("=",)),
    ("ASSIGN_OP", ("+=",)),
    ("ASSIGN_OP", ("-=",)),
    ("ASSIGN_OP", ("*=",)),
    ("ASSIGN_OP", ("/=",)),
    ("ASSIGN_OP", ("%=",)),
    ("ASSIGN_OP", ("&=",)),
    ("ASSIGN_OP", ("|=",)),
    ("ASSIGN_OP", ("^=",)),
    ("ASSIGN_OP", ("<<=",)),
    ("ASSIGN_OP", (">>=",)),

    ("LVALUE", ("ID",)),
    ("LVALUE", ("*", "ID")),
    ("LVALUE", ("POSTFIX", "[", "EXPR", "]")),
    ("LVALUE", ("POSTFIX", ".", "ID")),
    ("LVALUE", ("POSTFIX", "->", "ID")),

    # Binary Expressions
    ("BIN_EXPR", ("BIN_EXPR", "BIN_OP", "UNARY")),
    ("BIN_EXPR", ("UNARY",)),

    ("BIN_OP", ("+",)),
    ("BIN_OP", ("-",)),
    ("BIN_OP", ("*",)),
    ("BIN_OP", ("/",)),
    ("BIN_OP", ("%",)),
    ("BIN_OP", ("==",)),
    ("BIN_OP", ("!=",)),
    ("BIN_OP", ("<",)),
    ("BIN_OP", (">",)),
    ("BIN_OP", ("<=",)),
    ("BIN_OP", (">=",)),
    ("BIN_OP", ("&&",)),
    ("BIN_OP", ("||",)),
    ("BIN_OP", ("&",)),
    ("BIN_OP", ("|",)),
    ("BIN_OP", ("^",)),
    ("BIN_OP", ("<<",)),
    ("BIN_OP", (">>",)),

    # Unary & Postfix Expressions
    ("UNARY", ("UNARY_OP", "UNARY")),
    ("UNARY", ("sizeof", "(", "TYPE", ")")),
    ("UNARY", ("sizeof", "(", "EXPR", ")")),
    ("UNARY", ("sizeof", "UNARY")),
    ("UNARY", ("POSTFIX",)),

    ("UNARY_OP", ("+",)),
    ("UNARY_OP", ("-",)),
    ("UNARY_OP", ("!",)),
    ("UNARY_OP", ("~",)),
    ("UNARY_OP", ("*",)),
    ("UNARY_OP", ("&",)),
    ("UNARY_OP", ("++",)),
    ("UNARY_OP", ("--",)),

    ("POSTFIX", ("POSTFIX", "++")),
    ("POSTFIX", ("POSTFIX", "--")),
    ("POSTFIX", ("POSTFIX", "(", ")")),
    ("POSTFIX", ("POSTFIX", "(", "ARGLIST", ")")),
    ("POSTFIX", ("POSTFIX", "[", "EXPR", "]")),
    ("POSTFIX", ("POSTFIX", ".", "ID")),
    ("POSTFIX", ("POSTFIX", "->", "ID")),
    ("POSTFIX", ("PRIMARY",)),

    ("PRIMARY", ("(", "EXPR", ")")),
    ("PRIMARY", ("ID",)),
    ("PRIMARY", ("NUM",)),
    ("PRIMARY", ("STR",)),
    ("PRIMARY", ("CHAR",)),
    ("PRIMARY", ("NULL",)),

    ("ARGLIST", ("ARGLIST", ",", "EXPR")),
    ("ARGLIST", ("EXPR",)),
]

START_SYMBOL = "PROGRAM"


class Grammar:
    """Represents the C CFG with fast production lookup by LHS non-terminal."""

    def __init__(self, rules=None, start=None):
        self.rules = rules if rules is not None else GRAMMAR_RULES
        self.start = start or START_SYMBOL
        self.rules_by_lhs = defaultdict(list)
        for lhs, rhs in self.rules:
            self.rules_by_lhs[lhs].append(rhs)
        self.nonterminals = set(self.rules_by_lhs.keys())
        all_syms = {sym for _, rhs in self.rules for sym in rhs}
        self.terminals = all_syms - self.nonterminals

    def is_nonterminal(self, symbol: str) -> bool:
        return symbol in self.nonterminals

    def is_terminal(self, symbol: str) -> bool:
        return not self.is_nonterminal(symbol)

    def productions_for(self, lhs: str) -> list:
        return self.rules_by_lhs.get(lhs, [])

    def all_keywords(self) -> set:
        """Return all keyword terminals."""
        return {t for t in self.terminals if t.isalpha()}


# ── C Keywords & Lexical Categories ─────────────────────────────────────────

C_TYPE_KEYWORDS = {
    "int", "char", "float", "double", "void",
    "short", "long", "unsigned", "signed", "struct"
}

C_CONTROL_KEYWORDS = {
    "if", "else", "while", "for", "do",
    "switch", "case", "default",
    "return", "break", "continue"
}

C_OTHER_KEYWORDS = {"sizeof", "NULL"}

KEYWORDS = C_TYPE_KEYWORDS | C_CONTROL_KEYWORDS | C_OTHER_KEYWORDS

# ── C Tokenizer ─────────────────────────────────────────────────────────────

TOKEN_SPEC = [
    ("COMMENT_MULTI",  r"/\*[\s\S]*?\*/"),
    ("COMMENT_SINGLE", r"//[^\n]*"),
    ("PREPROCESSOR",   r"#[^\n]*"),
    ("STR",            r'"(?:[^"\\]|\\.)*"'),
    ("CHAR",           r"'(?:[^'\\]|\\.)*'"),
    ("NUM_HEX",        r"0[xX][0-9a-fA-F]+[uUlL]*"),
    ("NUM",            r"\d+(\.\d+)?([eE][+-]?\d+)?[fFlLuU]*"),
    ("ID",             r"[A-Za-z_][A-Za-z0-9_]*"),
    ("OP_ARROW",       r"->"),
    ("OP_COMPOUND",    r"<<=|>>=|\+\+|--|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>"),
    ("PUNCT",          r"[+\-*/%=(){}<>,;!&|^~:?\.\[\]]"),
    ("NEWLINE",        r"\n"),
    ("SKIP",           r"[ \t\r]+"),
    ("MISMATCH",       r"."),
]

TOKEN_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in TOKEN_SPEC))


class Token:
    """Represents a token with position and lexical info."""
    def __init__(self, symbol: str, raw: str, line: int, col: int, start: int, end: int):
        self.symbol = symbol  # Grammar terminal symbol e.g. 'int', 'ID', '+', ';'
        self.raw    = raw     # Source text
        self.line   = line    # 1-based line number
        self.col    = col     # 1-based column number
        self.start  = start   # 0-based character start index
        self.end    = end     # 0-based character end index

    def __repr__(self):
        return f"Token({self.symbol!r}, {self.raw!r}, L{self.line}:C{self.col})"

    def to_tuple(self):
        return (self.symbol, self.raw)


def tokenize(text: str, strict: bool = False) -> list:
    """
    Tokenize C source code into a list of Token objects.
    Preserves line/column information for syntax error reporting.
    """
    tokens = []
    line_num = 1
    line_start = 0

    for m in TOKEN_RE.finditer(text):
        kind = m.lastgroup
        raw  = m.group()
        start = m.start()
        end   = m.end()
        col   = start - line_start + 1

        if kind == "NEWLINE":
            line_num += 1
            line_start = end
            continue
        if kind in ("SKIP", "COMMENT_SINGLE", "COMMENT_MULTI", "PREPROCESSOR"):
            if "\n" in raw:
                line_num += raw.count("\n")
                line_start = start + raw.rfind("\n") + 1
            continue
        if kind == "MISMATCH":
            if strict:
                raise ValueError(f"Unexpected character {raw!r} at Line {line_num}, Col {col}")
            continue

        if kind in ("STR", "CHAR"):
            tokens.append(Token(kind, raw, line_num, col, start, end))
        elif kind in ("NUM", "NUM_HEX"):
            tokens.append(Token("NUM", raw, line_num, col, start, end))
        elif kind == "ID":
            if raw in KEYWORDS:
                tokens.append(Token(raw, raw, line_num, col, start, end))
            else:
                tokens.append(Token("ID", raw, line_num, col, start, end))
        else:
            # Operators, arrows, punctuation
            tokens.append(Token(raw, raw, line_num, col, start, end))

    return tokens


def get_token_stream(text: str) -> list:
    """Return terminal symbol list for Earley parser."""
    return [t.symbol for t in tokenize(text)]
