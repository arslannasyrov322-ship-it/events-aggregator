class Master:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Мастер {self.name} на связи"

arslan = Master("Арслан")
print(arslan.greet())

