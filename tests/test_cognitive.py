"""Calibration of the cognitive-complexity / nesting scanner.

The Java expectations are PMD 7.27.0's CognitiveComplexity values for these exact methods
(category/java/design.xml, reportLevel 1), so the lexical estimator is pinned to the reference
implementation the study's `pmd_method_Cognitive15` oracle later measures it against in the
field. The Python and Ruby expectations are hand-worked from Campbell's rules. Nesting values
are the real structural depths of the fixtures.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from complexity_concentration_study import cognitive

BIG_DEEP = """    public int deep(int x) {
        int s = 0;
        for (int a = 0; a < x; a++) { for (int b = 0; b < x; b++) { for (int c = 0; c < x; c++) {
            if (a > b) { if (b > c) { if (c > 1) { s++; } else { s--; } } else if (a == c) { s += 2; } }
            if (a < b && b < c || a == 0) { s += 3; } else if (c % 2 == 0) { s -= 1; } else { s *= 2; }
            if (s > 100 && x > 2) { s = 0; } if (s < -100 || x < 0) { s = 1; } if (a + b + c > 10) { s += 7; }
            switch (s % 5) { case 0: s++; break; case 1: s--; break; case 2: s += 2; break; case 3: s -= 2; break; default: s = 0; }
        } } }
        return s;
    }"""
CHAIN = """    public int chain(int x, List<Integer> xs) {
        int s = 0;
        if (x > 1) { s = 1; } else if (x > 2) { s = 2; } else if (x > 3) { s = 3; } else { s = 4; }
        for (int v : xs) { s += v > 0 ? 1 : 0; }
        xs.forEach(v -> { if (v > 10) { s2++; } });
        try { s = s / x; } catch (ArithmeticException e) { s = -1; } finally { s++; }
        while (s > 0 && x > 0 && xs.size() > 0 || s < -5) { s--; }
        do { s++; } while (s < 3);
        return s;
    }"""
NESTED = """    public int nested(int a, int b) {
        if (a > 0) {
            if (b > 0) {
                for (int i = 0; i < a; i++) {
                    if (i == b) { return i; }
                }
            }
        }
        return a > b ? a : (b > 0 ? b : 0);
    }"""
BOOLS = """    public int bools(boolean a, boolean b, boolean c, boolean d) {
        if (a && b && c || d) { return 1; }
        if (a && !b || c && d) { return 2; }
        return 0;
    }"""


def test_java_matches_pmd_cognitive_complexity():
    # (PMD CognitiveComplexity value, structural nesting depth)
    assert cognitive.analyze(BIG_DEEP, "java") == (49, 6)
    assert cognitive.analyze(CHAIN, "java") == (14, 2)
    assert cognitive.analyze(NESTED, "java") == (13, 4)
    assert cognitive.analyze(BOOLS, "java") == (7, 1)
    assert cognitive.analyze("public int small(int x) { return x + 1; }", "java") == (0, 0)


def test_do_while_tail_is_not_a_second_loop_and_a_later_while_is():
    src = "void f(){ do { x++; } while (x < 3); while (y) { y--; } }"
    assert cognitive.analyze(src, "c") == (2, 1)


def test_braceless_statement_does_not_leak_nesting_into_a_later_block():
    src = "int f(int a,int b){ if (a) return 1; { if (b) { return 2; } } return 0; }"
    assert cognitive.analyze(src, "c") == (2, 1)


def test_go_for_header_semicolons_keep_the_block_nesting():
    go = ("func deep(x, y, z, w, v int) int {\n s := 0\n for a := 0; a < x; a++ {\n  if a > y {\n"
          "   for s < z {\n    if s%2 == 0 && a > 1 || w > 3 { s += 2 } else { s += 1 }\n"
          "    if s > 100 { return s }\n   }\n  } else if a == v { panic(\"x\") }\n }\n return s\n}\n")
    # for(1) if(2) for(3) if(4)+&&+||, else(1), if(4), else-if(1) = 18; depth 4
    assert cognitive.analyze(go, "go") == (18, 4)


def test_typescript_optional_chaining_is_not_a_ternary():
    assert cognitive.analyze("function f(a){ return a?.b ?? (a ? 1 : 2); }", "ts") == (1, 1)


def test_python_follows_campbell():
    py = '''def f(x, xs):
    s = 0
    for a in xs:
        if a > x:
            try:
                while s < 10:
                    s += 1 if a else 2
            except ValueError:
                s = -1
        elif a == 0 and x > 1 or s:
            s = 5
        else:
            def g(y):
                if y:
                    return 1
            s = g(a)
    return s
'''
    # for 1; if 2; try 0; while 3; ternary 4; except 3; elif 1 + and/or 2; else 1; nested def 0;
    # if inside it 1 + (for, else, def) 3 = 4  -> 21; depth: for > else > def > if = 4
    assert cognitive.analyze(py, "py") == (21, 4)
    assert cognitive.analyze("def small(x):\n    return x + 1\n", "py") == (0, 0)


def test_ruby_blocks_modifiers_and_case():
    rb = '''  def deep(x)
    s = 0
    x.times do |a|
      if a > 1
        while s < 10
          s += 1 if a.even?
          case s
          when 1 then s += 2
          when 2 then s += 3
          else s -= 1
          end
        end
      elsif a == 0
        s = 5
      else
        s = 7
      end
    end
    return s unless s > 100 && x > 2 || s < 0
    s
  end'''
    # do-block nests 1; if 2; while 3; modifier-if 4; case 4; else 1; elsif 1; else 1;
    # modifier-unless 1 + && 1 + || 1 = 19; depth: do > if > while > case = 4
    assert cognitive.analyze(rb, "rb") == (19, 4)
    assert cognitive.analyze("  def small(x)\n    x + 1\n  end", "rb") == (0, 0)


def test_empty_source_is_zero():
    assert cognitive.analyze("", "java") == (0, 0)
    assert cognitive.cognitive_complexity("   \n") == 0
    assert cognitive.max_nesting_depth("   \n") == 0


if __name__ == "__main__":
    ok = True
    for k, fn in sorted(globals().items()):
        if k.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                ok = False
                print(f"  [FAIL] {fn.__name__}: {e}")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
