class DslValidationError(Exception):
    def __init__(self, code: str, message: str, path: str = ""):
        self.code = code
        self.message = message
        self.path = path
        location = f"{path}: " if path else ""
        super().__init__(f"{location}{code}: {message}")
