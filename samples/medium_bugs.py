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
