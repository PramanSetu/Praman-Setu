# Praman Setu — full agent-by-agent workflow output

**File:** `medium_bugs.py`  ·  **Final status:** `clean`  ·  **Passes:** 1

## 0. Original (input) code

```python
def calculate_grade(scores):
    total = 0
    for s in scores:
        total += s
    average = total / len(scores)
    if average >= 90
        return "A"
    elif average > 80:
        return "B"
    elif average >= 70:
        return "C"
    else:
        return "F"

def apply_discount(price, percent):
    return price - percent

def find_max(numbers):
    max_val = 0
    for n in numbers:
        if n > max_val:
            max_val = n
    return max_val

print(calculate_grade([95, 85, 75]))
print(apply_discount(100, 20))
print(find_max([-5, -2, -10]))
```

## 1. Input Handler (initial reproduction)

- **status:** `execution_failed`
- **error_type:** `SyntaxError`
- **error_line:** `6`
- **error_message:** SyntaxError: expected ':'

## Pass 1

### 2. Bug Ledger (deterministic static analysis)

```text
code_compiles: False
runtime_error: SyntaxError at line 6: SyntaxError: expected ':'
functions: <none>
classes: <none>
imports:
<none>
top_level_executable_lines: []
top_level_input_lines: []
issues:
- syntax line=6: SyntaxError: expected ':' symbol=SyntaxError
```

### 3. Patcher Agent (MultiIssueFixer)

- **summary:** Fixed the missing colon in the if statement at line 6.
- **confidence:** `0.95`
- **issues_found:** ['SyntaxError at line 6: missing colon after if condition']
- **units returned:** 1

  **Unit 1 — target `<file>`** — _(no reason given)_
```python
def calculate_grade(scores):
    total = 0
    for s in scores:
        total += s
    average = total / len(scores)
    if average >= 90:
        return "A"
    elif average > 80:
        return "B"
    elif average >= 70:
        return "C"
    else:
        return "F"

def apply_discount(price, percent):
    return price - percent

def find_max(numbers):
    max_val = 0
    for n in numbers:
        if n > max_val:
            max_val = n
    return max_val

print(calculate_grade([95, 85, 75]))
print(apply_discount(100, 20))
print(find_max([-5, -2, -10]))
```

### 4. Patch Applier (AST unit splice)

- **units applied:** 1
- **apply failures:** _(none)_

### 5. Validator (compile · sandbox run · security · tests)

- **validation errors:** _(none — passed)_

## 6. Final repaired code

```python
def calculate_grade(scores):
    total = 0
    for s in scores:
        total += s
    average = total / len(scores)
    if average >= 90:
        return "A"
    elif average > 80:
        return "B"
    elif average >= 70:
        return "C"
    else:
        return "F"

def apply_discount(price, percent):
    return price - percent

def find_max(numbers):
    max_val = 0
    for n in numbers:
        if n > max_val:
            max_val = n
    return max_val

print(calculate_grade([95, 85, 75]))
print(apply_discount(100, 20))
print(find_max([-5, -2, -10]))
```

## 7. Explainer Agent (user-facing narrative)

- **headline:** The code was repaired to fix a syntax error.
- **verification:** Verified in the sandbox: the file compiles, runs without errors, and passes the security scan.

**Fixes:**
- _[SyntaxError]_ missing colon after if condition → added a colon (:) at the end of the if statement

**Flagged (narrative):**
- _(none)_

## 8. Critic Agent (semantic review)

- **overall:** `risky`
- **summary:** The repair fixes a syntax error but does not address latent logic bugs

**Per-fix assessments:**
- `calculate_grade` — root_cause=True, intent=True, confidence=high
- `apply_discount` — root_cause=False, intent=False, confidence=low
  - concern: Discount calculation is incorrect, should be percentage of price
- `find_max` — root_cause=True, intent=True, confidence=low
  - concern: Initial value of max_val is 0, which may not be correct for all-negative input

**Latent logic audit (whole-program):**
- _[high]_ `apply_discount` — Discount calculation is incorrect, should be percentage of price
- _[medium]_ `find_max` — Initial value of max_val is 0, which may not be correct for all-negative input

**Needs human review (authoritative):**
- Review apply_discount to ensure correct discount calculation
- Review find_max to handle all-negative input correctly
