students = ["Sahil", "Rahul", "Priya"]
marks = [85, 90, 78]


def calculate_average(numbers):
    total = 0
    for num in numbers:
        total += num
    return total / len(numbers)

def display_students():
    print("Student List:")
    for i in range(len(students)):
        print(students[i])

def add_student(name, mark):
    students.append(name)
    marks.append(mark)

def find_student(name):
    for i in range(len(students)):
        if students[i] == name:
            return i
    return -1

average = calculate_average(marks)
print("Average Marks:", average)
display_students()
student_name = input("Enter student name: ")
index = find_student(student_name)
if index != -1:
    print("Marks:", marks[index])
else:
    print("Student not found")

try:
    age = int(input("Enter age: "))
    if age == 0:
        print("Age cannot be zero.")
    else:
        result = 100 / age
        print("Result:", result)
except ValueError:
    print("Invalid input for age.")

data = {"name": "Sahil", "course": "MCA"}
print("Name:", data.get("name", "Not found"))
print("Course:", data.get("course", "Not found"))
print("College:", data.get("college", "Not found"))

number = "50"
try:
    number = int(number)
    total = number + 10
    print("Total:", total)
except ValueError:
    print("Invalid number format.")
