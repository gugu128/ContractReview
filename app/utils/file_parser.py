from pathlib import Path


class FileParser:
    @staticmethod
    def read_text(path: str | Path, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding)
