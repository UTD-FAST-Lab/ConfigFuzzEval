class CodeBuilder:
    def __init__(self):
        self.code_ = str()

    def write_line(self, line: str, indent: int = 0, new_line: int = 1) -> None:
        self.code_ += ('    ' * indent) + line
        self.write_new_line(new_line)

    def write_block(self, block: str) -> None:
        self.code_ += block

    def write_new_line(self, lines: int) -> None:
        self.code_ += '\n' * lines

    def code(self) -> str:
        return self.code_
