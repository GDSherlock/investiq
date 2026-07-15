"""Dedicated lexer/parser and closed `calc-ir-v1` validator."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from typing import Any, Iterable, Sequence

from openpyxl.utils.cell import coordinate_to_tuple

from .function_registry import FUNCTION_REGISTRY
from .types import (
    CalculationRuleExtractionConfiguration,
    FormulaCompilation,
    FormulaIdFactory,
    FormulaReference,
    WorkbookCatalog,
    WorkbookFormulaCell,
    normalize_a1,
)


_NUMBER_PATTERN = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_\\\u0080-\uffff][A-Za-z0-9_.\\\u0080-\uffff]*")
_REFERENCE_PATTERN = re.compile(
    r"""
    (?:(?P<sheet>
        '(?:[^']|'')+'
        |(?:\[[^\]]+\])?[A-Za-z_\u0080-\uffff][^!+\-*/^%=<>&(),;:{}\s]*
    )!)?
    (?P<start>\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})
    (?::(?P<end>\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}))?
    """,
    re.VERBOSE,
)
_CELL_INTERSECTION_PATTERN = re.compile(
    r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}\s+\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}"
)
_WHOLE_COLUMN_PATTERN = re.compile(
    r"(?:(?:'(?:[^']|'')+'|[A-Za-z_][^!\s]*)!)?\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}"
)
_WHOLE_ROW_PATTERN = re.compile(
    r"(?:(?:'(?:[^']|'')+'|[A-Za-z_][^!\s]*)!)?\$?[1-9][0-9]*:\$?[1-9][0-9]*"
)
_THREE_DIMENSIONAL_PATTERN = re.compile(
    r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_. ]*)\s*:\s*"
    r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_. ]*)!"
)
_STRUCTURED_REFERENCE_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\[[^\]]+\]")
_ERROR_CODES = (
    "#DIV/0!",
    "#VALUE!",
    "#NAME?",
    "#NULL!",
    "#REF!",
    "#NUM!",
    "#N/A",
)
class _FormulaSyntaxError(ValueError):
    """Raised when the dedicated formula grammar rejects the token stream."""


class _UnsupportedFormula(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int


class _FormulaLexer:
    _TWO_CHARACTER_OPERATORS = {"<=", ">=", "<>"}
    _SINGLE_CHARACTER_TOKENS = {
        "+": "PLUS",
        "-": "MINUS",
        "*": "STAR",
        "/": "SLASH",
        "^": "CARET",
        "%": "PERCENT",
        "=": "EQUAL",
        "<": "LESS",
        ">": "GREATER",
        "(": "LPAREN",
        ")": "RPAREN",
        ",": "COMMA",
        "&": "AMPERSAND",
        ":": "COLON",
        "{": "LBRACE",
        "}": "RBRACE",
        ";": "SEMICOLON",
        "[": "LBRACKET",
        "]": "RBRACKET",
        "!": "BANG",
    }

    def tokenize(self, formula: str) -> tuple[_Token, ...]:
        if not formula.startswith("="):
            raise _FormulaSyntaxError("Formula must begin with '='")
        tokens: list[_Token] = []
        index = 1
        while index < len(formula):
            character = formula[index]
            if character.isspace():
                index += 1
                continue

            reference_match = _REFERENCE_PATTERN.match(formula, index)
            if reference_match is not None:
                end = reference_match.end()
                tokens.append(_Token("REFERENCE", formula[index:end], index, end))
                index = end
                continue

            if character == '"':
                end = index + 1
                while end < len(formula):
                    if formula[end] == '"':
                        if end + 1 < len(formula) and formula[end + 1] == '"':
                            end += 2
                            continue
                        end += 1
                        break
                    end += 1
                else:
                    raise _FormulaSyntaxError("Unterminated text literal")
                tokens.append(_Token("STRING", formula[index:end], index, end))
                index = end
                continue

            error_code = next(
                (code for code in _ERROR_CODES if formula.startswith(code, index)),
                None,
            )
            if error_code is not None:
                end = index + len(error_code)
                tokens.append(_Token("ERROR", error_code, index, end))
                index = end
                continue

            number_match = _NUMBER_PATTERN.match(formula, index)
            if number_match is not None:
                end = number_match.end()
                tokens.append(_Token("NUMBER", formula[index:end], index, end))
                index = end
                continue

            identifier_match = _IDENTIFIER_PATTERN.match(formula, index)
            if identifier_match is not None:
                end = identifier_match.end()
                tokens.append(_Token("IDENTIFIER", formula[index:end], index, end))
                index = end
                continue

            two_character = formula[index : index + 2]
            if two_character in self._TWO_CHARACTER_OPERATORS:
                tokens.append(_Token("COMPARISON", two_character, index, index + 2))
                index += 2
                continue
            token_kind = self._SINGLE_CHARACTER_TOKENS.get(character)
            if token_kind is not None:
                tokens.append(_Token(token_kind, character, index, index + 1))
                index += 1
                continue
            raise _UnsupportedFormula(f"unsupported_symbol:{character}")
        tokens.append(_Token("EOF", "", len(formula), len(formula)))
        return tuple(tokens)


class FormulaCompiler:
    def __init__(
        self,
        configuration: CalculationRuleExtractionConfiguration | None = None,
    ):
        self._configuration = configuration or CalculationRuleExtractionConfiguration()
        self._lexer = _FormulaLexer()
        self._validator = CalculationExpressionValidator()

    def compile(
        self,
        formula_cell: WorkbookFormulaCell,
        workbook_catalog: WorkbookCatalog,
    ) -> FormulaCompilation:
        expression_id = FormulaIdFactory.expression_id(
            formula_cell.id,
            self._configuration.ir_version,
            self._configuration.compiler_version,
            self._configuration.semantics_profile,
            formula_cell.formula_sha256,
        )
        if formula_cell.formula_kind != "scalar":
            return self._unsupported(
                formula_cell,
                expression_id,
                (),
                "not_attempted",
                "special_formula",
                (f"special_formula:{formula_cell.formula_kind}",),
            )
        if len(formula_cell.exact_formula) > self._configuration.max_formula_length:
            return self._unsupported(
                formula_cell,
                expression_id,
                (),
                "not_attempted",
                "unsupported",
                ("formula_length_limit",),
            )

        try:
            tokens = self._lexer.tokenize(formula_cell.exact_formula)
        except _UnsupportedFormula as exc:
            return self._unsupported(
                formula_cell,
                expression_id,
                (),
                "not_attempted",
                "unsupported",
                (exc.code,),
            )
        except _FormulaSyntaxError:
            return self._unsupported(
                formula_cell,
                expression_id,
                (),
                "syntax_error",
                "unsupported",
                ("syntax_error",),
            )

        references = self._references(
            tokens,
            formula_cell,
            workbook_catalog,
            expression_id,
        )
        if len(tokens) - 1 > self._configuration.max_tokens:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "not_attempted",
                "unsupported",
                ("token_limit",),
            )

        static_exclusion = self._static_exclusion(formula_cell.exact_formula)
        if static_exclusion is not None:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "not_attempted",
                "unsupported",
                (static_exclusion,),
            )

        external_references = tuple(
            reference for reference in references if reference.resolution_status == "external"
        )
        if external_references:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "external_reference",
                tuple(
                    f"external_reference:{reference.source_token}"
                    for reference in external_references
                ),
            )

        unresolved = tuple(
            reference
            for reference in references
            if reference.resolution_status != "resolved_internal"
        )
        if unresolved:
            reasons = tuple(
                reference.warning_code
                or f"{reference.resolution_status}:{reference.target_sheet_name or reference.source_token}"
                for reference in unresolved
            )
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "unsupported",
                reasons,
            )

        parser = _FormulaParser(tokens, references, formula_cell, self._configuration)
        try:
            root = parser.parse()
        except _UnsupportedFormula as exc:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "unsupported",
                (exc.code,),
            )
        except _FormulaSyntaxError:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "syntax_error",
                "unsupported",
                ("syntax_error",),
            )
        except RecursionError:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "unsupported",
                ("nesting_limit",),
            )

        try:
            normalized_signature = _normalized_signature(root, formula_cell)
        except RecursionError:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "unsupported",
                ("nesting_limit",),
            )
        expression = {
            "expression_id": expression_id,
            "formula_cell_id": formula_cell.id,
            "ir_version": self._configuration.ir_version,
            "compiler_version": self._configuration.compiler_version,
            "semantics_profile": self._configuration.semantics_profile,
            "formula_sha256": formula_cell.formula_sha256,
            "normalized_signature": normalized_signature,
            "root": root,
        }
        try:
            self._validator.validate(
                expression,
                formula_cell,
                references,
                self._configuration,
            )
        except ValueError as exc:
            return self._unsupported(
                formula_cell,
                expression_id,
                references,
                "parsed",
                "unsupported",
                (f"ir_validation:{str(exc)}",),
            )
        return FormulaCompilation(
            expression_id=expression_id,
            formula_cell_id=formula_cell.id,
            ir_version=self._configuration.ir_version,
            compiler_version=self._configuration.compiler_version,
            semantics_profile=self._configuration.semantics_profile,
            formula_sha256=formula_cell.formula_sha256,
            normalized_signature=normalized_signature,
            parse_status="parsed",
            support_status="supported",
            ir_json=expression,
            references=references,
            unsupported_constructs=(),
            warnings=(),
        )

    def _references(
        self,
        tokens: Sequence[_Token],
        formula_cell: WorkbookFormulaCell,
        catalog: WorkbookCatalog,
        expression_id: str,
    ) -> tuple[FormulaReference, ...]:
        references: list[FormulaReference] = []
        for token in tokens:
            if token.kind != "REFERENCE":
                continue
            references.append(
                self._reference(
                    token,
                    len(references),
                    formula_cell,
                    catalog,
                    expression_id,
                )
            )
        return tuple(references)

    def _reference(
        self,
        token: _Token,
        ordinal: int,
        formula_cell: WorkbookFormulaCell,
        catalog: WorkbookCatalog,
        expression_id: str,
    ) -> FormulaReference:
        match = _REFERENCE_PATTERN.fullmatch(token.value)
        if match is None:
            raise _FormulaSyntaxError("Invalid reference token")
        sheet_token = match.group("sheet")
        start_token = match.group("start")
        end_token = match.group("end")
        external = bool(sheet_token and "[" in sheet_token and "]" in sheet_token)
        target_sheet_name = (
            _unquote_sheet(sheet_token)
            if sheet_token is not None
            else formula_cell.ref.sheet_name
        )
        start_col_absolute, start_row_absolute = _cell_anchor_flags(start_token)
        try:
            start_address: str | None = _parse_cell_token(start_token)[0]
        except ValueError:
            start_address = None
        end_address: str | None = None
        end_col_absolute: bool | None = None
        end_row_absolute: bool | None = None
        rows: int | None = None
        columns: int | None = None
        resolution_status = (
            "resolved_internal" if start_address is not None else "invalid_address"
        )
        target_classification = (
            "internal" if start_address is not None else "unresolved"
        )
        target_sheet_position: int | None = None
        warning_code: str | None = (
            None if start_address is not None else "invalid_address"
        )

        if end_token is not None:
            end_col_absolute, end_row_absolute = _cell_anchor_flags(end_token)
            try:
                end_address = _parse_cell_token(end_token)[0]
            except ValueError:
                end_address = None
                resolution_status = "invalid_address"
                target_classification = "unresolved"
                warning_code = "invalid_address"
            if start_address is not None and end_address is not None:
                start_row, start_column = coordinate_to_tuple(start_address)
                end_row, end_column = coordinate_to_tuple(end_address)
                if end_row < start_row or end_column < start_column:
                    resolution_status = "unsupported"
                    warning_code = "range_must_be_ordered"
                else:
                    rows = end_row - start_row + 1
                    columns = end_column - start_column + 1
                    if rows * columns > self._configuration.max_range_cells:
                        resolution_status = "unsupported"
                        warning_code = "range_cell_limit"

        if external:
            target_classification = "external"
            resolution_status = "external"
            target_sheet_position = None
        else:
            target_sheet_position = catalog.sheet_position(target_sheet_name)
            if target_sheet_position is None and resolution_status == "resolved_internal":
                target_classification = "unresolved"
                resolution_status = "missing_sheet"

        reference_kind = "range" if end_token is not None else "cell"
        normalized_target = f"{target_sheet_name}!{start_address or start_token.upper()}"
        if end_token is not None:
            normalized_target += f":{end_address or end_token.upper()}"
        reference_id = FormulaIdFactory.reference_id(
            formula_cell.id,
            expression_id,
            ordinal,
            (token.start, token.end),
            reference_kind,
            normalized_target,
        )
        return FormulaReference(
            id=reference_id,
            expression_id=expression_id,
            formula_cell_id=formula_cell.id,
            workbook_version_id=formula_cell.ref.workbook_version_id,
            ordinal=ordinal,
            source_token=token.value,
            source_span_start=token.start,
            source_span_end=token.end,
            reference_kind=reference_kind,
            target_classification=target_classification,
            target_sheet_name=target_sheet_name,
            target_sheet_position=target_sheet_position,
            start_cell_address=start_address,
            end_cell_address=end_address,
            start_column_absolute=start_col_absolute,
            start_row_absolute=start_row_absolute,
            end_column_absolute=end_col_absolute,
            end_row_absolute=end_row_absolute,
            range_rows=rows,
            range_columns=columns,
            resolution_status=resolution_status,
            warning_code=warning_code,
        )

    @staticmethod
    def _static_exclusion(formula: str) -> str | None:
        visible = _mask_text_literals(formula)
        if _THREE_DIMENSIONAL_PATTERN.search(visible):
            return "three_dimensional_reference"
        if _WHOLE_COLUMN_PATTERN.search(visible):
            return "whole_column_reference"
        if _WHOLE_ROW_PATTERN.search(visible):
            return "whole_row_reference"
        if _STRUCTURED_REFERENCE_PATTERN.search(visible):
            return "structured_reference"
        if _CELL_INTERSECTION_PATTERN.search(visible):
            return "reference_intersection"
        if "&" in visible:
            return "text_concatenation"
        if "{" in visible or "}" in visible:
            return "array_constant"
        if ";" in visible:
            return "unsupported_argument_separator"
        return None

    def _unsupported(
        self,
        formula_cell: WorkbookFormulaCell,
        expression_id: str,
        references: tuple[FormulaReference, ...],
        parse_status: str,
        support_status: str,
        constructs: tuple[str, ...],
    ) -> FormulaCompilation:
        return FormulaCompilation(
            expression_id=expression_id,
            formula_cell_id=formula_cell.id,
            ir_version=self._configuration.ir_version,
            compiler_version=self._configuration.compiler_version,
            semantics_profile=self._configuration.semantics_profile,
            formula_sha256=formula_cell.formula_sha256,
            normalized_signature=None,
            parse_status=parse_status,
            support_status=support_status,
            ir_json=None,
            references=references,
            unsupported_constructs=constructs,
            warnings=(),
        )


class _FormulaParser:
    _COMPARISON_OPERATOR = {
        "=": "equal",
        "<>": "not_equal",
        "<": "less",
        "<=": "less_equal",
        ">": "greater",
        ">=": "greater_equal",
    }
    _BINARY_OPERATOR = {
        "+": "add",
        "-": "subtract",
        "*": "multiply",
        "/": "divide",
        "^": "power",
    }

    def __init__(
        self,
        tokens: Sequence[_Token],
        references: Sequence[FormulaReference],
        formula_cell: WorkbookFormulaCell,
        configuration: CalculationRuleExtractionConfiguration,
    ):
        self._tokens = tokens
        self._index = 0
        self._references = {reference.source_span: reference for reference in references}
        self._formula_cell = formula_cell
        self._configuration = configuration
        self._node_count = 0

    def parse(self) -> dict[str, Any]:
        if self._peek().kind == "EOF":
            raise _FormulaSyntaxError("Empty formula")
        root = self._comparison()
        if self._peek().kind == "COMMA":
            raise _UnsupportedFormula("reference_union")
        if self._peek().kind != "EOF":
            token = self._peek()
            if token.kind == "AMPERSAND":
                raise _UnsupportedFormula("text_concatenation")
            raise _FormulaSyntaxError(f"Unexpected token {token.value}")
        return root

    def _comparison(self) -> dict[str, Any]:
        node = self._additive()
        while self._peek().value in self._COMPARISON_OPERATOR:
            operator = self._advance()
            right = self._additive()
            node = self._node(
                "comparison",
                (node["source_span"]["start"], right["source_span"]["end"]),
                operator=self._COMPARISON_OPERATOR[operator.value],
                left=node,
                right=right,
            )
        return node

    def _additive(self) -> dict[str, Any]:
        node = self._multiplicative()
        while self._peek().kind in {"PLUS", "MINUS"}:
            operator = self._advance()
            right = self._multiplicative()
            node = self._node(
                "binary_operation",
                (node["source_span"]["start"], right["source_span"]["end"]),
                operator=self._BINARY_OPERATOR[operator.value],
                left=node,
                right=right,
            )
        return node

    def _multiplicative(self) -> dict[str, Any]:
        node = self._power()
        while self._peek().kind in {"STAR", "SLASH"}:
            operator = self._advance()
            right = self._power()
            node = self._node(
                "binary_operation",
                (node["source_span"]["start"], right["source_span"]["end"]),
                operator=self._BINARY_OPERATOR[operator.value],
                left=node,
                right=right,
            )
        return node

    def _power(self) -> dict[str, Any]:
        node = self._percent()
        while self._peek().kind == "CARET":
            self._advance()
            right = self._percent()
            node = self._node(
                "binary_operation",
                (node["source_span"]["start"], right["source_span"]["end"]),
                operator="power",
                left=node,
                right=right,
            )
        return node

    def _percent(self) -> dict[str, Any]:
        node = self._unary()
        while self._peek().kind == "PERCENT":
            percent = self._advance()
            node = self._node(
                "unary_operation",
                (node["source_span"]["start"], percent.end),
                operator="percent",
                operand=node,
            )
        return node

    def _unary(self) -> dict[str, Any]:
        if self._peek().kind in {"PLUS", "MINUS"}:
            operator = self._advance()
            operand = self._unary()
            return self._node(
                "unary_operation",
                (operator.start, operand["source_span"]["end"]),
                operator="positive" if operator.kind == "PLUS" else "negative",
                operand=operand,
            )
        return self._primary()

    def _primary(self) -> dict[str, Any]:
        token = self._advance()
        if token.kind == "NUMBER":
            try:
                decimal = Decimal(token.value)
            except InvalidOperation as exc:
                raise _FormulaSyntaxError("Invalid numeric literal") from exc
            if not decimal.is_finite():
                raise _UnsupportedFormula("non_finite_literal")
            value = _canonical_decimal(decimal)
            return self._node(
                "literal",
                (token.start, token.end),
                literal_type="number",
                value=value,
                lexeme=token.value,
            )
        if token.kind == "STRING":
            value = token.value[1:-1].replace('""', '"')
            return self._node(
                "literal",
                (token.start, token.end),
                literal_type="text",
                value=value,
                lexeme=token.value,
            )
        if token.kind == "ERROR":
            return self._node(
                "error_value",
                (token.start, token.end),
                error_code=token.value,
            )
        if token.kind == "REFERENCE":
            reference = self._references[(token.start, token.end)]
            if reference.reference_kind == "cell":
                return self._node(
                    "cell_reference",
                    (token.start, token.end),
                    reference_id=reference.id,
                    cell=_cell_json(reference, end=False),
                )
            return self._node(
                "range_reference",
                (token.start, token.end),
                reference_id=reference.id,
                start_cell=_cell_json(reference, end=False),
                end_cell=_cell_json(reference, end=True),
                rows=reference.range_rows,
                columns=reference.range_columns,
            )
        if token.kind == "IDENTIFIER":
            upper = token.value.upper()
            if upper in {"TRUE", "FALSE"} and self._peek().kind != "LPAREN":
                return self._node(
                    "literal",
                    (token.start, token.end),
                    literal_type="boolean",
                    value=upper == "TRUE",
                    lexeme=token.value,
                )
            if self._peek().kind != "LPAREN":
                raise _UnsupportedFormula(f"named_reference:{token.value}")
            return self._function(token)
        if token.kind == "LPAREN":
            node = self._comparison()
            self._expect("RPAREN")
            return node
        if token.kind == "EOF":
            raise _FormulaSyntaxError("Expected expression")
        raise _FormulaSyntaxError(f"Unexpected token {token.value}")

    def _function(self, name_token: _Token) -> dict[str, Any]:
        function_name = name_token.value.upper()
        self._expect("LPAREN")
        arguments: list[dict[str, Any]] = []
        if self._peek().kind != "RPAREN":
            while True:
                arguments.append(self._comparison())
                if self._peek().kind != "COMMA":
                    break
                self._advance()
                if self._peek().kind == "RPAREN":
                    raise _FormulaSyntaxError("Missing function argument")
        closing = self._expect("RPAREN")
        if len(arguments) > self._configuration.max_arguments:
            raise _UnsupportedFormula("argument_limit")
        definition = FUNCTION_REGISTRY.get(function_name)
        if definition is None:
            raise _UnsupportedFormula(f"unsupported_function:{function_name}")
        if not definition.minimum_arguments <= len(arguments) <= definition.maximum_arguments:
            raise _UnsupportedFormula(f"invalid_arity:{function_name}")
        return self._node(
            "function_call",
            (name_token.start, closing.end),
            function_name=function_name,
            arguments=arguments,
        )

    def _node(self, node_type: str, span: tuple[int, int], **fields: Any) -> dict[str, Any]:
        self._node_count += 1
        if self._node_count > self._configuration.max_nodes:
            raise _UnsupportedFormula("node_limit")
        node = {
            "node_type": node_type,
            "source_span": {"start": span[0], "end": span[1]},
        }
        node.update(fields)
        return node

    def _peek(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._peek()
        if token.kind != "EOF":
            self._index += 1
        return token

    def _expect(self, kind: str) -> _Token:
        token = self._advance()
        if token.kind != kind:
            raise _FormulaSyntaxError(f"Expected {kind}")
        return token


class CalculationExpressionValidator:
    _NODE_FIELDS: dict[str, tuple[set[str], set[str]]] = {
        "literal": (
            {"node_type", "source_span", "literal_type", "value"},
            {"lexeme"},
        ),
        "error_value": (
            {"node_type", "source_span", "error_code"},
            set(),
        ),
        "cell_reference": (
            {"node_type", "source_span", "reference_id", "cell"},
            set(),
        ),
        "range_reference": (
            {
                "node_type",
                "source_span",
                "reference_id",
                "start_cell",
                "end_cell",
                "rows",
                "columns",
            },
            set(),
        ),
        "binary_operation": (
            {"node_type", "source_span", "operator", "left", "right"},
            set(),
        ),
        "unary_operation": (
            {"node_type", "source_span", "operator", "operand"},
            set(),
        ),
        "comparison": (
            {"node_type", "source_span", "operator", "left", "right"},
            set(),
        ),
        "function_call": (
            {"node_type", "source_span", "function_name", "arguments"},
            set(),
        ),
    }

    def validate(
        self,
        expression: dict[str, Any] | None,
        formula_cell: WorkbookFormulaCell,
        references: Sequence[FormulaReference],
        configuration: CalculationRuleExtractionConfiguration,
    ) -> None:
        if not isinstance(expression, dict):
            raise ValueError("Calculation expression must be an object")
        if (
            not formula_cell.exact_formula.startswith("=")
            or len(formula_cell.exact_formula) > configuration.max_formula_length
        ):
            raise ValueError("Calculation formula source is invalid")
        formula_hash = sha256(formula_cell.exact_formula.encode("utf-8")).hexdigest()
        if formula_cell.formula_sha256 != formula_hash:
            raise ValueError("Calculation formula source hash does not match")
        expected_formula_cell_id = FormulaIdFactory(
            formula_cell.ref.workbook_version_id
        ).formula_cell_id(formula_cell.ref)
        if formula_cell.id != expected_formula_cell_id:
            raise ValueError("Calculation formula cell identity does not match")
        expected_envelope = {
            "expression_id",
            "formula_cell_id",
            "ir_version",
            "compiler_version",
            "semantics_profile",
            "formula_sha256",
            "normalized_signature",
            "root",
        }
        if set(expression) != expected_envelope:
            raise ValueError("Calculation expression envelope fields are invalid")
        if expression["formula_cell_id"] != formula_cell.id:
            raise ValueError("Calculation expression formula cell does not match")
        if expression["formula_sha256"] != formula_cell.formula_sha256:
            raise ValueError("Calculation expression formula hash does not match")
        if expression["ir_version"] != configuration.ir_version:
            raise ValueError("Calculation expression IR version is not registered")
        if expression["compiler_version"] != configuration.compiler_version:
            raise ValueError("Calculation expression compiler version is not registered")
        if expression["semantics_profile"] != configuration.semantics_profile:
            raise ValueError("Calculation expression semantics profile is not registered")
        expected_id = FormulaIdFactory.expression_id(
            formula_cell.id,
            configuration.ir_version,
            configuration.compiler_version,
            configuration.semantics_profile,
            formula_cell.formula_sha256,
        )
        if expression["expression_id"] != expected_id:
            raise ValueError("Calculation expression identity does not match")
        self._validate_reference_evidence(
            references,
            expression["expression_id"],
            formula_cell,
        )
        reference_by_id = {reference.id: reference for reference in references}
        state: dict[str, Any] = {"count": 0, "reference_ids": set()}
        self._validate_node(
            expression["root"],
            formula_cell,
            reference_by_id,
            configuration,
            depth=1,
            state=state,
        )
        if state["reference_ids"] != set(reference_by_id):
            raise ValueError("Calculation expression reference evidence is incomplete")
        root_span = expression["root"]["source_span"]
        outside_root = (
            formula_cell.exact_formula[1 : root_span["start"]]
            + formula_cell.exact_formula[root_span["end"] :]
        )
        if re.sub(r"[()\s]", "", outside_root):
            raise ValueError("Calculation root source span is incomplete")
        if expression["normalized_signature"] != _normalized_signature(
            expression["root"],
            formula_cell,
        ):
            raise ValueError("Calculation expression normalized signature does not match")

    @staticmethod
    def _validate_reference_evidence(
        references: Sequence[FormulaReference],
        expression_id: str,
        formula_cell: WorkbookFormulaCell,
    ) -> None:
        if len({reference.id for reference in references}) != len(references):
            raise ValueError("Calculation expression reference identities are duplicated")
        if [reference.ordinal for reference in references] != list(range(len(references))):
            raise ValueError("Calculation expression reference ordinals are invalid")
        previous_end = -1
        for reference in sorted(references, key=lambda item: item.source_span):
            if reference.formula_cell_id != formula_cell.id:
                raise ValueError("Calculation expression reference formula cell does not match")
            if reference.expression_id != expression_id:
                raise ValueError("Calculation expression reference owner does not match")
            if reference.workbook_version_id != formula_cell.ref.workbook_version_id:
                raise ValueError("Calculation expression reference workbook does not match")
            start, end = reference.source_span
            if not 0 <= start < end <= len(formula_cell.exact_formula):
                raise ValueError("Calculation expression reference source span is invalid")
            if start < previous_end:
                raise ValueError("Calculation expression reference source spans overlap")
            previous_end = end
            if formula_cell.exact_formula[start:end] != reference.source_token:
                raise ValueError("Calculation expression reference source token does not match")
            expected_id = FormulaIdFactory.reference_id(
                formula_cell.id,
                expression_id,
                reference.ordinal,
                reference.source_span,
                reference.reference_kind,
                reference.normalized_target,
            )
            if reference.id != expected_id:
                raise ValueError("Calculation expression reference identity does not match")
            if (
                reference.target_classification != "internal"
                or reference.resolution_status != "resolved_internal"
                or reference.target_sheet_name is None
                or reference.target_sheet_position is None
                or reference.start_cell_address is None
            ):
                raise ValueError("Executable reference is missing or unresolved")

    def _validate_node(
        self,
        node: Any,
        formula_cell: WorkbookFormulaCell,
        reference_by_id: dict[str, FormulaReference],
        configuration: CalculationRuleExtractionConfiguration,
        *,
        depth: int,
        state: dict[str, Any],
    ) -> None:
        if not isinstance(node, dict):
            raise ValueError("Calculation node must be an object")
        node_type = node.get("node_type")
        if node_type not in self._NODE_FIELDS:
            raise ValueError(f"Unknown calculation node type: {node_type}")
        required, optional = self._NODE_FIELDS[node_type]
        actual_fields = set(node)
        if not required <= actual_fields or actual_fields - required - optional:
            raise ValueError(f"Invalid fields for calculation node type: {node_type}")
        span = node["source_span"]
        if not isinstance(span, dict) or set(span) != {"start", "end"}:
            raise ValueError("Calculation node source span is invalid")
        start, end = span["start"], span["end"]
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Calculation node source span must contain integers")
        if not 0 <= start < end <= len(formula_cell.exact_formula):
            raise ValueError("Calculation node source span is out of bounds")
        state["count"] += 1
        if state["count"] > configuration.max_nodes:
            raise ValueError("Calculation expression exceeds node limit")
        if depth > configuration.max_depth:
            raise ValueError("Calculation expression exceeds nesting limit")

        if node_type == "literal":
            if node["literal_type"] not in {"number", "boolean", "text", "blank"}:
                raise ValueError("Unknown literal type")
            source = formula_cell.exact_formula[start:end]
            if node["literal_type"] == "number":
                if not isinstance(node["value"], str):
                    raise ValueError("Numeric literal must use canonical decimal text")
                try:
                    number = Decimal(node["value"])
                except (InvalidOperation, TypeError) as exc:
                    raise ValueError("Numeric literal is invalid") from exc
                if not number.is_finite():
                    raise ValueError("Numeric literal must be finite")
                try:
                    source_number = Decimal(source)
                except InvalidOperation as exc:
                    raise ValueError(
                        "Literal source span does not match numeric value"
                    ) from exc
                if _canonical_decimal(source_number) != node["value"]:
                    raise ValueError("Literal source span does not match numeric value")
            elif node["literal_type"] == "boolean":
                if not isinstance(node["value"], bool):
                    raise ValueError("Boolean literal must contain a boolean value")
                if source.upper() not in {"TRUE", "FALSE"} or (
                    source.upper() == "TRUE"
                ) != node["value"]:
                    raise ValueError("Literal source span does not match boolean value")
            elif node["literal_type"] == "text":
                if not isinstance(node["value"], str):
                    raise ValueError("Text literal must contain text")
                if (
                    len(source) < 2
                    or not source.startswith('"')
                    or not source.endswith('"')
                    or source[1:-1].replace('""', '"') != node["value"]
                ):
                    raise ValueError("Literal source span does not match text value")
            elif node["value"] is not None:
                raise ValueError("Blank literal must contain null")
        elif node_type == "error_value":
            if node["error_code"] not in _ERROR_CODES:
                raise ValueError("Unknown Excel error code")
            if formula_cell.exact_formula[start:end] != node["error_code"]:
                raise ValueError("Error literal source span does not match")
        elif node_type in {"cell_reference", "range_reference"}:
            reference = reference_by_id.get(node["reference_id"])
            if reference is None or reference.resolution_status != "resolved_internal":
                raise ValueError("Executable reference is missing or unresolved")
            if reference.source_span != (start, end):
                raise ValueError("Executable reference span does not match evidence")
            expected_kind = "cell" if node_type == "cell_reference" else "range"
            if reference.reference_kind != expected_kind:
                raise ValueError("Executable reference kind does not match evidence")
            state["reference_ids"].add(reference.id)
            if node_type == "cell_reference" and node["cell"] != _cell_json(
                reference,
                end=False,
            ):
                raise ValueError("Executable reference target does not match evidence")
            if node_type == "range_reference":
                if (
                    node["start_cell"] != _cell_json(reference, end=False)
                    or node["end_cell"] != _cell_json(reference, end=True)
                ):
                    raise ValueError("Executable reference target does not match evidence")
                if node["rows"] != reference.range_rows or node["columns"] != reference.range_columns:
                    raise ValueError("Executable range shape does not match evidence")
                if node["rows"] * node["columns"] > configuration.max_range_cells:
                    raise ValueError("Executable range exceeds cell limit")
        elif node_type == "binary_operation":
            if node["operator"] not in {"add", "subtract", "multiply", "divide", "power"}:
                raise ValueError("Unknown binary operator")
            self._children(node, ("left", "right"), formula_cell, reference_by_id, configuration, depth, state)
            self._validate_infix_source(
                node,
                formula_cell,
                {
                    "add": "+",
                    "subtract": "-",
                    "multiply": "*",
                    "divide": "/",
                    "power": "^",
                }[node["operator"]],
            )
        elif node_type == "unary_operation":
            if node["operator"] not in {"positive", "negative", "percent"}:
                raise ValueError("Unknown unary operator")
            self._children(node, ("operand",), formula_cell, reference_by_id, configuration, depth, state)
            operand_span = node["operand"]["source_span"]
            if node["operator"] == "percent":
                operator_source = formula_cell.exact_formula[operand_span["end"] : end]
                expected_operator = "%"
            else:
                operator_source = formula_cell.exact_formula[start : operand_span["start"]]
                expected_operator = "+" if node["operator"] == "positive" else "-"
            if _operator_source(operator_source) != expected_operator:
                raise ValueError("Calculation unary operator source does not match")
        elif node_type == "comparison":
            if node["operator"] not in {"equal", "not_equal", "less", "less_equal", "greater", "greater_equal"}:
                raise ValueError("Unknown comparison operator")
            self._children(node, ("left", "right"), formula_cell, reference_by_id, configuration, depth, state)
            self._validate_infix_source(
                node,
                formula_cell,
                {
                    "equal": "=",
                    "not_equal": "<>",
                    "less": "<",
                    "less_equal": "<=",
                    "greater": ">",
                    "greater_equal": ">=",
                }[node["operator"]],
            )
        elif node_type == "function_call":
            function_name = node["function_name"]
            definition = FUNCTION_REGISTRY.get(function_name)
            if definition is None:
                raise ValueError("Unknown calculation function")
            arguments = node["arguments"]
            if not isinstance(arguments, list) or len(arguments) > configuration.max_arguments:
                raise ValueError("Function arguments are invalid")
            if not definition.minimum_arguments <= len(arguments) <= definition.maximum_arguments:
                raise ValueError("Function arity is invalid")
            for child in arguments:
                self._validate_node(
                    child,
                    formula_cell,
                    reference_by_id,
                    configuration,
                    depth=depth + 1,
                    state=state,
                )
            self._validate_child_spans(node, arguments)
            self._validate_function_source(node, formula_cell, function_name)

    def _children(
        self,
        node: dict[str, Any],
        fields: Iterable[str],
        formula_cell: WorkbookFormulaCell,
        reference_by_id: dict[str, FormulaReference],
        configuration: CalculationRuleExtractionConfiguration,
        depth: int,
        state: dict[str, Any],
    ) -> None:
        children = [node[field_name] for field_name in fields]
        for child in children:
            self._validate_node(
                child,
                formula_cell,
                reference_by_id,
                configuration,
                depth=depth + 1,
                state=state,
            )
        self._validate_child_spans(node, children)

    @staticmethod
    def _validate_child_spans(
        node: dict[str, Any],
        children: Sequence[dict[str, Any]],
    ) -> None:
        parent_start = node["source_span"]["start"]
        parent_end = node["source_span"]["end"]
        previous_end = parent_start
        for child in children:
            child_start = child["source_span"]["start"]
            child_end = child["source_span"]["end"]
            if child_start < parent_start or child_end > parent_end:
                raise ValueError("Calculation child source span is outside its parent")
            if child_start < previous_end:
                raise ValueError("Calculation child source spans overlap")
            previous_end = child_end

    @staticmethod
    def _validate_infix_source(
        node: dict[str, Any],
        formula_cell: WorkbookFormulaCell,
        expected_operator: str,
    ) -> None:
        left_end = node["left"]["source_span"]["end"]
        right_start = node["right"]["source_span"]["start"]
        source = formula_cell.exact_formula[left_end:right_start]
        if _operator_source(source) != expected_operator:
            raise ValueError("Calculation operator source does not match")

    @staticmethod
    def _validate_function_source(
        node: dict[str, Any],
        formula_cell: WorkbookFormulaCell,
        function_name: str,
    ) -> None:
        start = node["source_span"]["start"]
        end = node["source_span"]["end"]
        arguments = node["arguments"]
        if not arguments:
            compact = re.sub(r"\s", "", formula_cell.exact_formula[start:end])
            if compact.upper() != f"{function_name}()":
                raise ValueError("Calculation function argument source does not match")
            return

        first_start = arguments[0]["source_span"]["start"]
        prefix = re.sub(
            r"\s",
            "",
            formula_cell.exact_formula[start:first_start],
        )
        if not prefix.upper().startswith(function_name):
            raise ValueError("Calculation function source does not match")
        opening = prefix[len(function_name) :]
        if not opening or set(opening) != {"("}:
            raise ValueError("Calculation function argument source does not match")
        for left, right in zip(arguments, arguments[1:]):
            separator = formula_cell.exact_formula[
                left["source_span"]["end"] : right["source_span"]["start"]
            ]
            if _operator_source(separator) != ",":
                raise ValueError("Calculation function argument source does not match")
        suffix = re.sub(
            r"\s",
            "",
            formula_cell.exact_formula[arguments[-1]["source_span"]["end"] : end],
        )
        if not suffix or set(suffix) != {")"}:
            raise ValueError("Calculation function argument source does not match")


def _parse_cell_token(token: str) -> tuple[str, bool, bool]:
    match = re.fullmatch(r"(\$?)([A-Za-z]{1,3})(\$?)([1-9][0-9]{0,6})", token)
    if match is None:
        raise _FormulaSyntaxError("Invalid A1 reference")
    column_anchor, column_text, row_anchor, row_text = match.groups()
    address = normalize_a1(f"{column_text}{row_text}")
    return address, bool(column_anchor), bool(row_anchor)


def _cell_anchor_flags(token: str) -> tuple[bool, bool]:
    match = re.fullmatch(r"(\$?)[A-Za-z]{1,3}(\$?)[1-9][0-9]{0,6}", token)
    if match is None:
        raise _FormulaSyntaxError("Invalid A1 reference")
    return bool(match.group(1)), bool(match.group(2))


def _operator_source(source: str) -> str:
    """Discard only syntactic grouping/whitespace around an operator token."""
    return re.sub(r"[()\s]", "", source)


def _unquote_sheet(sheet_token: str) -> str:
    if sheet_token.startswith("'") and sheet_token.endswith("'"):
        return sheet_token[1:-1].replace("''", "'")
    return sheet_token


def _cell_json(reference: FormulaReference, *, end: bool) -> dict[str, Any]:
    if end:
        cell_address = reference.end_cell_address
        column_absolute = reference.end_column_absolute
        row_absolute = reference.end_row_absolute
    else:
        cell_address = reference.start_cell_address
        column_absolute = reference.start_column_absolute
        row_absolute = reference.start_row_absolute
    return {
        "workbook_version_id": _workbook_id_from_reference(reference),
        "sheet_name": reference.target_sheet_name,
        "sheet_position": reference.target_sheet_position,
        "cell_address": cell_address,
        "column_absolute": column_absolute,
        "row_absolute": row_absolute,
    }


def _workbook_id_from_reference(reference: FormulaReference) -> str:
    return reference.workbook_version_id


def _mask_text_literals(formula: str) -> str:
    characters = list(formula)
    index = 0
    while index < len(characters):
        if characters[index] != '"':
            index += 1
            continue
        index += 1
        while index < len(characters):
            if characters[index] == '"':
                if index + 1 < len(characters) and characters[index + 1] == '"':
                    characters[index] = " "
                    characters[index + 1] = " "
                    index += 2
                    continue
                characters[index] = " "
                index += 1
                break
            characters[index] = " "
            index += 1
    return "".join(characters)


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = format(value.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _normalized_signature(node: dict[str, Any], formula_cell: WorkbookFormulaCell) -> str:
    node_type = node["node_type"]
    if node_type == "literal":
        return f"literal:{node['literal_type']}:{node['value']}"
    if node_type == "error_value":
        return f"error:{node['error_code']}"
    if node_type == "cell_reference":
        return f"ref:{_relative_cell_signature(node['cell'], formula_cell)}"
    if node_type == "range_reference":
        return "range:" + ":".join(
            (
                _relative_cell_signature(node["start_cell"], formula_cell),
                _relative_cell_signature(node["end_cell"], formula_cell),
            )
        )
    if node_type in {"binary_operation", "comparison"}:
        return (
            f"{node['operator']}("
            f"{_normalized_signature(node['left'], formula_cell)},"
            f"{_normalized_signature(node['right'], formula_cell)})"
        )
    if node_type == "unary_operation":
        return f"{node['operator']}({_normalized_signature(node['operand'], formula_cell)})"
    if node_type == "function_call":
        arguments = ",".join(
            _normalized_signature(argument, formula_cell)
            for argument in node["arguments"]
        )
        return f"{node['function_name']}({arguments})"
    raise ValueError(f"Unknown node type: {node_type}")


def _relative_cell_signature(cell: dict[str, Any], formula_cell: WorkbookFormulaCell) -> str:
    target_row, target_column = coordinate_to_tuple(cell["cell_address"])
    source_row, source_column = coordinate_to_tuple(formula_cell.ref.cell_address)
    row = f"R{target_row}" if cell["row_absolute"] else f"R[{target_row - source_row}]"
    column = (
        f"C{target_column}"
        if cell["column_absolute"]
        else f"C[{target_column - source_column}]"
    )
    return f"{cell['sheet_name']}!{row}{column}"
