"""
earley.py
Earley Parser with Error Detection, Panic-Mode Recovery, and Analysis.

Each Earley state is (lhs, rhs, dot, origin):
    lhs    -> Non-terminal symbol being parsed
    rhs    -> Tuple of RHS symbols in the production
    dot    -> Integer index indicating current match progress
    origin -> Chart column where parsing of this production began

Operations:
    - PREDICTION: Adds new candidate states for the non-terminal following the dot.
    - SCANNING:   Advances states whose next expected symbol matches the input token.
    - COMPLETION: Advances caller states from the origin column when a production finishes.

Enhancements:
    - O(1) state lookup and insertion queue per chart column.
    - Incomplete-prefix tolerance: keeps live states in the final column for autocompletion.
    - Error detection & diagnostics: records unexpected tokens and expected grammar terminals.
    - Error recovery: synchronization on statement boundaries (';', '}', '{').
"""

from collections import namedtuple

State = namedtuple("State", ["lhs", "rhs", "dot", "origin"])


def next_symbol(state: State):
    """Return symbol immediately after the dot, or None if the state is complete."""
    return state.rhs[state.dot] if state.dot < len(state.rhs) else None


def is_complete(state: State) -> bool:
    """Return True if the state has matched all symbols in its RHS."""
    return state.dot >= len(state.rhs)


def advance(state: State) -> State:
    """Advance the dot by one position."""
    return State(state.lhs, state.rhs, state.dot + 1, state.origin)


def state_key(state: State) -> str:
    """Canonical unique key for state deduplication."""
    return f"{state.lhs}|{'~'.join(state.rhs)}|{state.dot}|{state.origin}"


class EarleyParser:
    """
    Earley parser that builds a full chart and reports active states,
    expected continuations, and syntax errors with recovery.
    """

    def __init__(self, grammar):
        self.grammar = grammar
        self._prod_cache = {}

    def _productions_for(self, lhs: str) -> list:
        if lhs not in self._prod_cache:
            self._prod_cache[lhs] = self.grammar.productions_for(lhs)
        return self._prod_cache[lhs]

    def _expand_column(self, chart: list, col_idx: int):
        """Execute Prediction and Completion until the column reaches a fixed point."""
        queue = list(chart[col_idx].values())
        head = 0

        while head < len(queue):
            state = queue[head]
            head += 1
            sym = next_symbol(state)

            if sym is None:
                # ── COMPLETION ────────────────────────────────────────────
                for caller in list(chart[state.origin].values()):
                    if next_symbol(caller) == state.lhs:
                        ns = advance(caller)
                        k = state_key(ns)
                        if k not in chart[col_idx]:
                            chart[col_idx][k] = ns
                            queue.append(ns)

            elif self.grammar.is_nonterminal(sym):
                # ── PREDICTION ────────────────────────────────────────────
                for rhs in self._productions_for(sym):
                    ns = State(sym, rhs, 0, col_idx)
                    k = state_key(ns)
                    if k not in chart[col_idx]:
                        chart[col_idx][k] = ns
                        queue.append(ns)

    def parse(self, terminals: list) -> list:
        """
        Run the standard Earley parsing algorithm on a list of terminal symbols.
        Returns the chart list (one column per token index + 1).
        """
        n = len(terminals)
        chart = [dict() for _ in range(n + 1)]

        # Seed column 0 with start-symbol productions
        for rhs in self._productions_for(self.grammar.start):
            s = State(self.grammar.start, rhs, 0, 0)
            chart[0][state_key(s)] = s

        self._expand_column(chart, 0)

        for i in range(n):
            tok = terminals[i]
            # ── SCANNING ──────────────────────────────────────────────────
            for state in chart[i].values():
                if next_symbol(state) == tok:
                    ns = advance(state)
                    k = state_key(ns)
                    chart[i + 1][k] = ns

            # Expand the newly scanned column
            self._expand_column(chart, i + 1)

            # If scanning produced no states, parsing has stalled at this token
            if not chart[i + 1]:
                break

        return chart

    def parse_with_analysis(self, terminals: list, tokens: list = None) -> dict:
        """
        Parse terminal sequence with syntax error detection and recovery.

        Returns a dictionary containing:
            - chart: The Earley chart constructed
            - consumed_tokens: Number of tokens successfully parsed
            - valid_prefix: True if all tokens parsed without stalling
            - is_complete_program: True if start symbol is completed at end
            - error: Dict with unexpected token details, expected symbols, line, col (or None)
            - expected_terminals: Set of terminals expected at the cursor/end
            - recovered: True if recovery occurred
        """
        n = len(terminals)
        chart = [dict() for _ in range(n + 1)]

        # Seed column 0
        for rhs in self._productions_for(self.grammar.start):
            s = State(self.grammar.start, rhs, 0, 0)
            chart[0][state_key(s)] = s

        self._expand_column(chart, 0)

        error_info = None
        consumed = 0
        recovered = False

        for i in range(n):
            tok = terminals[i]
            # Try to scan token
            scanned = False
            for state in chart[i].values():
                if next_symbol(state) == tok:
                    ns = advance(state)
                    k = state_key(ns)
                    chart[i + 1][k] = ns
                    scanned = True

            if scanned:
                self._expand_column(chart, i + 1)
                consumed += 1
            else:
                # Syntax error encountered at token index i
                expected = {next_symbol(s) for s in chart[i].values()
                            if next_symbol(s) and self.grammar.is_terminal(next_symbol(s))}

                tok_obj = tokens[i] if tokens and i < len(tokens) else None
                error_info = {
                    "token_index": i,
                    "unexpected_symbol": tok,
                    "raw": tok_obj.raw if tok_obj else tok,
                    "line": tok_obj.line if tok_obj else 1,
                    "col": tok_obj.col if tok_obj else (i + 1),
                    "expected_terminals": sorted(list(expected)),
                }

                # Attempt error recovery: Look ahead for synchronization token (';', '}', '{')
                sync_idx = None
                for j in range(i + 1, n):
                    if terminals[j] in (";", "}"):
                        sync_idx = j
                        break

                if sync_idx is not None:
                    # Reset chart at sync point to start a fresh statement/item
                    recovered = True
                    for rhs in self._productions_for("STMT"):
                        s = State("STMT", rhs, 0, sync_idx + 1)
                        chart[sync_idx + 1][state_key(s)] = s
                    for rhs in self._productions_for("DECL_ITEM"):
                        s = State("DECL_ITEM", rhs, 0, sync_idx + 1)
                        chart[sync_idx + 1][state_key(s)] = s
                    self._expand_column(chart, sync_idx + 1)
                    consumed = sync_idx + 1
                break

        last_col_idx = consumed
        last_states = list(chart[last_col_idx].values())

        expected_terminals = set()
        for s in last_states:
            sym = next_symbol(s)
            if sym is not None and self.grammar.is_terminal(sym):
                expected_terminals.add(sym)

        # Check if complete program accepted
        is_complete_prog = any(
            s.lhs == self.grammar.start and is_complete(s) and s.origin == 0
            for s in chart[len(terminals)].values()
        ) if consumed == n else False

        return {
            "chart": chart,
            "consumed_tokens": consumed,
            "valid_prefix": (consumed == n),
            "is_complete_program": is_complete_prog,
            "error": error_info,
            "expected_terminals": expected_terminals,
            "recovered": recovered,
        }

    def chart_summary(self, chart: list) -> list:
        """Return per-column metrics for frontend visualization."""
        summary = []
        for i, col in enumerate(chart):
            states = list(col.values())
            completed = sum(1 for s in states if is_complete(s))
            predicted = sum(1 for s in states if s.dot == 0 and s.origin == i)
            summary.append({
                "column": i,
                "count": len(states),
                "completed": completed,
                "predicted": predicted,
                "states": [
                    {
                        "lhs": s.lhs,
                        "rhs": list(s.rhs),
                        "dot": s.dot,
                        "origin": s.origin,
                        "is_complete": is_complete(s),
                        "next_sym": next_symbol(s)
                    }
                    for s in states
                ]
            })
        return summary
