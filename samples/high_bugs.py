class BankAccount:
    def __init__(self, balance=0):
        self.balance = balance
        self.history = []

    def deposit(self, amount):
        self.balance += amount
        self.history.append(("deposit", amount))

    def withdraw(self, amount)
        if amount > self.balance:
            return False
        self.balance -= amount
        self.history.append(("withdraw", amount))
        return True

    def apply_interest(self, rate):
        self.balance = self.balance * rate

def transfer(src, dst, amount):
    src.withdraw(amount)
    dst.deposit(amount)

def average_balance(accounts):
    total = 0
    for acc in accounts:
        total += acc.balance
    return total / len(accounts)

acc1 = BankAccount(100)
acc2 = BankAccount(50)
transfer(acc1, acc2, 200)
acc1.apply_interest(5)
print(acc1.balance, acc2.balance)
print(average_balance([acc1, acc2]))
