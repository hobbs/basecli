"""Recursive-descent parser producing an AST for the Bases grammar.

Precedence (low to high)::

    ||  |          logical or
    &&  &          logical and
    ==  !=         equality
    <  >  <=  >=   comparison
    +  -           additive
    *  /  %        multiplicative
    !  -           unary prefix
    . [] ()        member / index / call (postfix)
    primary        literals, identifiers, ( ), [ ], { }, /regexp/
"""

from __future__ import annotations

from typing import List, Optional

from .errors import ParseError
from .lexer import Token, tokenize


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------
class Node:
    __slots__ = ()


class Literal(Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Literal({self.value!r})"


class RegexpLit(Node):
    __slots__ = ("pattern", "flags")

    def __init__(self, pattern, flags):
        self.pattern = pattern
        self.flags = flags

    def __repr__(self):
        return f"RegexpLit(/{self.pattern}/{self.flags})"


class Identifier(Node):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Identifier({self.name})"


class ListLit(Node):
    __slots__ = ("elements",)

    def __init__(self, elements):
        self.elements = elements

    def __repr__(self):
        return f"ListLit({self.elements!r})"


class ObjectLit(Node):
    __slots__ = ("pairs",)

    def __init__(self, pairs):
        self.pairs = pairs  # list of (key_str, value_node)

    def __repr__(self):
        return f"ObjectLit({self.pairs!r})"


class Member(Node):
    __slots__ = ("obj", "name")

    def __init__(self, obj, name):
        self.obj = obj
        self.name = name

    def __repr__(self):
        return f"Member({self.obj!r}.{self.name})"


class Index(Node):
    __slots__ = ("obj", "index")

    def __init__(self, obj, index):
        self.obj = obj
        self.index = index

    def __repr__(self):
        return f"Index({self.obj!r}[{self.index!r}])"


class Call(Node):
    __slots__ = ("callee", "args")

    def __init__(self, callee, args):
        self.callee = callee
        self.args = args

    def __repr__(self):
        return f"Call({self.callee!r}, {self.args!r})"


class Unary(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"Unary({self.op}{self.operand!r})"


class Binary(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"Binary({self.left!r} {self.op} {self.right!r})"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self, tokens: List[Token], source: str = ""):
        self.tokens = tokens
        self.pos = 0
        self.source = source

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def next(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, ttype: str) -> Token:
        tok = self.peek()
        if tok.type != ttype:
            raise ParseError(
                f"Expected {ttype} but found {tok.type} ({tok.value!r})",
                {"pos": tok.pos, "source": self.source},
            )
        return self.next()

    def _is_op(self, *values) -> bool:
        tok = self.peek()
        return tok.type == "OP" and tok.value in values

    # -- entry --------------------------------------------------------------
    def parse(self) -> Node:
        node = self.parse_or()
        if self.peek().type != "EOF":
            tok = self.peek()
            raise ParseError(
                f"Unexpected trailing token {tok.type} ({tok.value!r})",
                {"pos": tok.pos, "source": self.source},
            )
        return node

    # -- precedence climbing -------------------------------------------------
    def parse_or(self) -> Node:
        left = self.parse_and()
        while self._is_op("||", "|"):
            self.next()
            right = self.parse_and()
            left = Binary("||", left, right)
        return left

    def parse_and(self) -> Node:
        left = self.parse_equality()
        while self._is_op("&&", "&"):
            self.next()
            right = self.parse_equality()
            left = Binary("&&", left, right)
        return left

    def parse_equality(self) -> Node:
        left = self.parse_comparison()
        while self._is_op("==", "!="):
            op = self.next().value
            right = self.parse_comparison()
            left = Binary(op, left, right)
        return left

    def parse_comparison(self) -> Node:
        left = self.parse_additive()
        while self.peek().type in ("OP",) and self.peek().value in ("<", ">", "<=", ">="):
            op = self.next().value
            right = self.parse_additive()
            left = Binary(op, left, right)
        return left

    def parse_additive(self) -> Node:
        left = self.parse_multiplicative()
        while self._is_op("+", "-"):
            op = self.next().value
            right = self.parse_multiplicative()
            left = Binary(op, left, right)
        return left

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary()
        while self._is_op("*", "/", "%"):
            op = self.next().value
            right = self.parse_unary()
            left = Binary(op, left, right)
        return left

    def parse_unary(self) -> Node:
        if self._is_op("!", "-"):
            op = self.next().value
            operand = self.parse_unary()
            return Unary(op, operand)
        return self.parse_postfix()

    def parse_postfix(self) -> Node:
        node = self.parse_primary()
        while True:
            tok = self.peek()
            if tok.type == "DOT":
                self.next()
                name_tok = self.peek()
                if name_tok.type not in ("IDENT", "BOOL", "NULL"):
                    raise ParseError(
                        f"Expected property name after '.', found {name_tok.type}",
                        {"pos": name_tok.pos, "source": self.source},
                    )
                self.next()
                name = name_tok.value if name_tok.type == "IDENT" else \
                    ("true" if name_tok.value is True else "false" if name_tok.value is False else "null")
                if self.peek().type == "LPAREN":
                    args = self.parse_args()
                    node = Call(Member(node, name), args)
                else:
                    node = Member(node, name)
            elif tok.type == "LBRACKET":
                self.next()
                index_expr = self.parse_or()
                self.expect("RBRACKET")
                node = Index(node, index_expr)
            elif tok.type == "LPAREN":
                args = self.parse_args()
                node = Call(node, args)
            else:
                break
        return node

    def parse_args(self) -> List[Node]:
        self.expect("LPAREN")
        args: List[Node] = []
        if self.peek().type != "RPAREN":
            args.append(self.parse_or())
            while self.peek().type == "COMMA":
                self.next()
                args.append(self.parse_or())
        self.expect("RPAREN")
        return args

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok.type == "NUMBER":
            self.next()
            return Literal(tok.value)
        if tok.type == "STRING":
            self.next()
            return Literal(tok.value)
        if tok.type == "BOOL":
            self.next()
            return Literal(tok.value)
        if tok.type == "NULL":
            self.next()
            return Literal(None)
        if tok.type == "REGEXP":
            self.next()
            pattern, flags = tok.value
            return RegexpLit(pattern, flags)
        if tok.type == "IDENT":
            self.next()
            return Identifier(tok.value)
        if tok.type == "LPAREN":
            self.next()
            node = self.parse_or()
            self.expect("RPAREN")
            return node
        if tok.type == "LBRACKET":
            return self.parse_list()
        if tok.type == "LBRACE":
            return self.parse_object()
        raise ParseError(
            f"Unexpected token {tok.type} ({tok.value!r})",
            {"pos": tok.pos, "source": self.source},
        )

    def parse_list(self) -> Node:
        self.expect("LBRACKET")
        elements: List[Node] = []
        if self.peek().type != "RBRACKET":
            elements.append(self.parse_or())
            while self.peek().type == "COMMA":
                self.next()
                if self.peek().type == "RBRACKET":
                    break
                elements.append(self.parse_or())
        self.expect("RBRACKET")
        return ListLit(elements)

    def parse_object(self) -> Node:
        self.expect("LBRACE")
        pairs = []
        if self.peek().type != "RBRACE":
            pairs.append(self._parse_object_entry())
            while self.peek().type == "COMMA":
                self.next()
                if self.peek().type == "RBRACE":
                    break
                pairs.append(self._parse_object_entry())
        self.expect("RBRACE")
        return ObjectLit(pairs)

    def _parse_object_entry(self):
        key_tok = self.peek()
        if key_tok.type == "STRING":
            self.next()
            key = key_tok.value
        elif key_tok.type == "IDENT":
            self.next()
            key = key_tok.value
        else:
            raise ParseError(
                f"Expected object key, found {key_tok.type}",
                {"pos": key_tok.pos, "source": self.source},
            )
        self.expect("COLON")
        value = self.parse_or()
        return (key, value)


_PARSE_CACHE = {}


def parse_expression(source: str) -> Node:
    """Parse a Bases expression string into an AST (memoized)."""
    if source in _PARSE_CACHE:
        return _PARSE_CACHE[source]
    tokens = tokenize(source)
    node = Parser(tokens, source).parse()
    _PARSE_CACHE[source] = node
    return node
