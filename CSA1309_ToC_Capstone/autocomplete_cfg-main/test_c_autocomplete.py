"""
test_c_autocomplete.py
Automated Verification Suite for C CFG Earley Autocomplete Engine.
"""

import sys
from grammar import Grammar, tokenize, KEYWORDS
from earley import EarleyParser
from autocomplete import AutocompleteEngine

def run_tests():
    engine = AutocompleteEngine()
    print("======================================================================")
    print(" RUNNING C CFG AUTOCOMPLETE ENGINE VERIFICATION SUITE")
    print(f" Loaded Grammar Rules: {len(engine.grammar.rules)}")
    print("======================================================================")

    all_passed = True
    tests = [
        {
            "name": "Empty Editor",
            "input": "",
            "check": lambda res: len(res["suggestions"]) > 0 and any(s["display"] == "int" for s in res["suggestions"]),
            "expected": "Expected C types and declaration starters"
        },
        {
            "name": "After 'int '",
            "input": "int ",
            "check": lambda res: any(s["display"] == "main" for s in res["suggestions"]) and any(s["display"] == "*" for s in res["suggestions"]),
            "expected": "'main' and pointer '*'"
        },
        {
            "name": "Typing 'int ma'",
            "input": "int ma",
            "check": lambda res: res["suggestions"][0]["display"] == "main",
            "expected": "'main' at top rank"
        },
        {
            "name": "After 'int main()'",
            "input": "int main()",
            "check": lambda res: any(s["display"] == "{" for s in res["suggestions"]) and any(s["display"] == ";" for s in res["suggestions"]),
            "expected": "'{' (block) and ';' (prototype)"
        },
        {
            "name": "Inside 'int main() {'",
            "input": "int main() {",
            "check": lambda res: any(s["display"] == "int" for s in res["suggestions"]) and any(s["display"] == "return" for s in res["suggestions"]),
            "expected": "C types ('int', 'char') and statement starters ('return', 'if')"
        },
        {
            "name": "Assignment 'int a ='",
            "input": "int a =",
            "check": lambda res: any(s["category"] == "literal" for s in res["suggestions"]) or any(s["category"] == "operator" for s in res["suggestions"]),
            "expected": "Expression starters and literals"
        },
        {
            "name": "Inside 'if ('",
            "input": "if (",
            "check": lambda res: any(s["category"] == "literal" for s in res["suggestions"]) and any(s["category"] == "operator" for s in res["suggestions"]),
            "expected": "Condition expression starters, unary ops, literals"
        },
        {
            "name": "Relational continuation 'if (a >'",
            "input": "if (a >",
            "check": lambda res: any(s["category"] == "literal" for s in res["suggestions"]) or any(s["category"] == "identifier" for s in res["suggestions"]),
            "expected": "RHS expression starters"
        },
        {
            "name": "For loop init 'for ('",
            "input": "for (",
            "check": lambda res: any(s["display"] == "int" for s in res["suggestions"]) and any(s["display"] == ";" for s in res["suggestions"]),
            "expected": "Loop initialization: types, expressions, or ';'"
        },
        {
            "name": "While condition 'while ('",
            "input": "while (",
            "check": lambda res: any(s["category"] == "literal" for s in res["suggestions"]) or any(s["category"] == "operator" for s in res["suggestions"]),
            "expected": "Expression condition starters"
        },
        {
            "name": "Function call 'printf('",
            "input": "printf(",
            "check": lambda res: any(s["display"] == ")" for s in res["suggestions"]) or any(s["display"] == "STR" for s in res["suggestions"]),
            "expected": "Arguments or ')'"
        },
        {
            "name": "Return statement 'return '",
            "input": "return ",
            "check": lambda res: any(s["display"] == ";" for s in res["suggestions"]) and any(s["category"] == "literal" for s in res["suggestions"]),
            "expected": "Return expression or ';'"
        },
        {
            "name": "Missing semicolon detection",
            "input": "int a = 5 \n int b = 10;",
            "check": lambda res: res["status"] in ("Syntax Error", "Recovered", "Incomplete"),
            "expected": "Error/incomplete status reported"
        },
        {
            "name": "Missing closing brace",
            "input": "int main() { int a = 5;",
            "check": lambda res: res["status"] == "Incomplete" and any("unclosed" in str(e).lower() or "brace" in str(e).lower() for e in res["errors"]),
            "expected": "Unclosed brace diagnostic"
        },
        {
            "name": "Invalid token handling",
            "input": "int a = @;",
            "check": lambda res: res["status"] in ("Syntax Error", "Incomplete", "Recovered"),
            "expected": "Does not crash on invalid char @"
        },
        {
            "name": "Nested if statements",
            "input": "if ( a > 0 ) { if ( b > 0 ) { return a + b ; } }",
            "check": lambda res: res["status"] == "Valid" or res["is_complete"],
            "expected": "Valid accepted program"
        },
        {
            "name": "Function declaration and call",
            "input": "int add(int x, int y); int main() { int res = add(1, 2); return res; }",
            "check": lambda res: res["status"] == "Valid" or res["is_complete"],
            "expected": "Valid complete C program"
        },
        {
            "name": "Variable scope tracking",
            "input": "int my_custom_var = 42;\nif (",
            "check": lambda res: any(s["display"] == "my_custom_var" for s in res["suggestions"]),
            "expected": "'my_custom_var' suggested in scope"
        }
    ]

    for idx, t in enumerate(tests, start=1):
        try:
            res = engine.suggest(t["input"])
            passed = t["check"](res)
            status_sym = "[PASS]" if passed else "[FAIL]"
            if not passed:
                all_passed = False
            top_suggs = [s["display"] for s in res["suggestions"][:6]]
            print(f"{status_sym} #{idx:02d}: {t['name']}")
            print(f"       Input       : {t['input']!r}")
            print(f"       Top Suggs   : {top_suggs}")
            print(f"       Status      : {res['status']} ({res['status_message']})")
            if not passed:
                print(f"       EXPECTED    : {t['expected']}")
        except Exception as e:
            all_passed = False
            print(f"[FAIL] #{idx:02d}: {t['name']} - CRASHED: {e}")

    print("======================================================================")
    if all_passed:
        print(" >>> ALL 18 VERIFICATION TEST CASES PASSED SUCCESSFULLY! <<<")
    else:
        print(" >>> SOME TESTS FAILED <<<")
    print("======================================================================")
    return all_passed

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
