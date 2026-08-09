"""Error classes for the drawing language interpreter (spec §3.3, §3.4, §8.3)."""


class DrawLangError(Exception):
    """Base class for all drawing-language errors."""

    def __init__(self, message: str, statement_index: int | None = None):
        super().__init__(message)
        self.message = message
        self.statement_index = statement_index

    def __str__(self) -> str:
        if self.statement_index is not None:
            return f"[statement #{self.statement_index}] {self.message}"
        return self.message


class LexicalError(DrawLangError):
    """
    Raised for unknown opcodes, unknown modifiers, malformed numbers,
    or any violation of the grammar in spec §3 and §10.
    """


class SemanticError(DrawLangError):
    """
    Raised for wrong argument count, wrong argument type, out-of-range values,
    or modifiers applied to opcodes that do not accept them (spec §6-§8).
    """
