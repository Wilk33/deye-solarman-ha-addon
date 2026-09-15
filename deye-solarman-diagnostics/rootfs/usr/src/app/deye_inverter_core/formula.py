from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Any
from typing import Callable

from .codec import apply_transform
from .codec import decode_registers


MAX_AST_NODES=300
MAX_LOOP_ITERATIONS=64
MAX_FUNCTION_CALL_DEPTH=8
MAX_REGISTER_READS=128
REGISTER_TYPES={"uint16","int16","uint32","int32","hex","ascii"}
WORD_ORDERS={"high_low","low_high"}
BYTE_ORDERS={"high_low","low_high"}
MATH_FUNCTIONS={"abs","min","max","round","sqrt","clamp"}


class FormulaError(ValueError):
	"""A user formula is invalid or cannot be evaluated safely."""


@dataclass(slots=True)
class FormulaRead:
	address: int
	raw_registers: list[int]
	register_type: str
	multiplier: float
	offset: float
	word_order: str
	byte_order: str
	decoded: int | str
	value: int | float | str


@dataclass(slots=True)
class FormulaResult:
	value: int | float | str | None
	reads: list[FormulaRead]


class _ReturnSignal(Exception):
	def __init__(self, value: int | float | str | None) -> None:
		self.value=value


@dataclass(slots=True)
class _FormulaFunction:
	node: ast.FunctionDef
	environment: dict[str, Any]


class _FormulaValidator(ast.NodeVisitor):
	def __init__(self) -> None:
		self.node_count=0
		self.function_names: set[str]=set()

	def validate(self, source: str) -> ast.FunctionDef:
		if not isinstance(source,str) or not source.strip():
			raise FormulaError("Formula must contain a return statement")
		wrapped="def __formula__():\n"+"\n".join("\t"+line for line in source.splitlines())
		try:
			tree=ast.parse(wrapped,mode="exec")
		except SyntaxError as error:
			raise FormulaError(f"Formula syntax error line {max(error.lineno-1,1)}: {error.msg}") from error
		if not tree.body or not isinstance(tree.body[0],ast.FunctionDef):
			raise FormulaError("Formula could not be parsed")
		self.function_names={node.name for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
		self.visit(tree)
		root=tree.body[0]
		if not any(isinstance(node,ast.Return) for node in ast.walk(root)):
			raise FormulaError("Formula must contain a return statement")
		return root

	def generic_visit(self, node: ast.AST) -> None:
		self.node_count+=1
		if self.node_count > MAX_AST_NODES:
			raise FormulaError(f"Formula exceeds the limit of {MAX_AST_NODES} syntax nodes")
		allowed=(
			ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Assign,ast.AugAssign,
			ast.Expr,ast.If,ast.For,ast.Match,ast.match_case,ast.MatchValue,ast.MatchSingleton,
			ast.MatchAs,ast.Pass,ast.Name,ast.Constant,ast.Call,ast.BinOp,ast.UnaryOp,
			ast.BoolOp,ast.Compare,ast.IfExp,ast.Load,ast.Store,ast.Add,ast.Sub,ast.Mult,
			ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.BitAnd,ast.BitOr,ast.BitXor,
			ast.LShift,ast.RShift,ast.USub,ast.UAdd,ast.Invert,ast.Not,ast.And,ast.Or,
			ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE,ast.In,ast.NotIn,ast.Is,ast.IsNot,
		)
		if not isinstance(node,allowed):
			raise FormulaError(f"Formula uses unsupported syntax: {type(node).__name__}")
		super().generic_visit(node)

	def visit_Call(self, node: ast.Call) -> None:
		if not isinstance(node.func,ast.Name):
			raise FormulaError("Only named formula functions are allowed")
		allowed={"sensor","RAW","range"}|MATH_FUNCTIONS|self.function_names
		if node.func.id not in allowed:
			raise FormulaError(f"Formula function is not allowed: {node.func.id}")
		if node.keywords:
			raise FormulaError("Formula functions do not accept keyword arguments")
		self.generic_visit(node)

	def visit_For(self, node: ast.For) -> None:
		if not isinstance(node.target,ast.Name):
			raise FormulaError("Formula for loop target must be a single variable")
		if not isinstance(node.iter,ast.Call) or not isinstance(node.iter.func,ast.Name) or node.iter.func.id != "range":
			raise FormulaError("Formula for loops only support range(...)")
		self.generic_visit(node)

	def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
		if node.decorator_list or node.args.defaults or node.args.kw_defaults or node.args.vararg or node.args.kwarg:
			raise FormulaError("Formula functions only support positional arguments without defaults")
		self.generic_visit(node)

	def visit_Assign(self, node: ast.Assign) -> None:
		if len(node.targets) != 1 or not isinstance(node.targets[0],ast.Name):
			raise FormulaError("Formula assignments require one local variable")
		self.generic_visit(node)

	def visit_AugAssign(self, node: ast.AugAssign) -> None:
		if not isinstance(node.target,ast.Name):
			raise FormulaError("Formula augmented assignments require one local variable")
		self.generic_visit(node)


def validate_formula(source: str) -> None:
	_FormulaValidator().validate(source)


class FormulaExecutor:
	def __init__(self, reader: Callable[[int,int], list[int]]) -> None:
		self._reader=reader
		self._cache: dict[int,int]={}
		self._reads: list[FormulaRead]=[]
		self._loop_iterations=0
		self._register_read_count=0
		self._call_stack: list[str]=[]

	def execute(self, source: str) -> FormulaResult:
		root=_FormulaValidator().validate(source)
		environment: dict[str, Any]={}
		try:
			self._execute_statements(root.body,environment)
		except _ReturnSignal as signal:
			return FormulaResult(self._result_value(signal.value),list(self._reads))
		raise FormulaError("Formula must return a scalar value")

	def _execute_statements(self, statements: list[ast.stmt], environment: dict[str, Any]) -> None:
		for statement in statements:
			self._execute_statement(statement,environment)

	def _execute_statement(self, statement: ast.stmt, environment: dict[str, Any]) -> None:
		if isinstance(statement,ast.Assign):
			target=statement.targets[0]
			assert isinstance(target,ast.Name)
			self._assert_local_name(target.id)
			environment[target.id]=self._evaluate(statement.value,environment)
			return
		if isinstance(statement,ast.AugAssign):
			assert isinstance(statement.target,ast.Name)
			self._assert_local_name(statement.target.id)
			if statement.target.id not in environment:
				raise FormulaError(f"Formula local variable is undefined: {statement.target.id}")
			environment[statement.target.id]=self._binary(
				statement.op,
				environment[statement.target.id],
				self._evaluate(statement.value,environment),
			)
			return
		if isinstance(statement,ast.Expr):
			self._evaluate(statement.value,environment)
			return
		if isinstance(statement,ast.Return):
			value=self._evaluate(statement.value,environment) if statement.value is not None else None
			raise _ReturnSignal(value)
		if isinstance(statement,ast.If):
			body=statement.body if self._evaluate(statement.test,environment) else statement.orelse
			self._execute_statements(body,environment)
			return
		if isinstance(statement,ast.For):
			assert isinstance(statement.target,ast.Name)
			values=self._evaluate(statement.iter,environment)
			if not isinstance(values,range):
				raise FormulaError("Formula for loops only support range(...)")
			for value in values:
				self._loop_iterations+=1
				if self._loop_iterations > MAX_LOOP_ITERATIONS:
					raise FormulaError(f"Formula loop exceeds {MAX_LOOP_ITERATIONS} iterations")
				environment[statement.target.id]=value
				self._execute_statements(statement.body,environment)
			self._execute_statements(statement.orelse,environment)
			return
		if isinstance(statement,ast.Match):
			subject=self._evaluate(statement.subject,environment)
			for case in statement.cases:
				if self._matches(case.pattern,subject,environment):
					self._execute_statements(case.body,environment)
					return
			return
		if isinstance(statement,ast.FunctionDef):
			self._assert_local_name(statement.name)
			environment[statement.name]=_FormulaFunction(statement,dict(environment))
			return
		if isinstance(statement,ast.Pass):
			return
		raise FormulaError(f"Formula statement is not supported: {type(statement).__name__}")

	def _evaluate(self, node: ast.expr, environment: dict[str, Any]) -> Any:
		if isinstance(node,ast.Constant):
			if type(node.value) not in {int,float,str,bool,type(None)}:
				raise FormulaError("Formula constant type is not supported")
			return node.value
		if isinstance(node,ast.Name):
			if node.id in environment:
				return environment[node.id]
			if node.id.startswith("R") and node.id[1:].isdigit():
				address=int(node.id[1:])
				if not 0 <= address <= 65535:
					raise FormulaError(f"Formula register is outside Modbus range: {node.id}")
				return address
			if node.id in REGISTER_TYPES|WORD_ORDERS:
				return node.id
			if node.id in MATH_FUNCTIONS|{"sensor","RAW","range"}:
				return node.id
			raise FormulaError(f"Formula name is undefined: {node.id}")
		if isinstance(node,ast.BinOp):
			return self._binary(node.op,self._evaluate(node.left,environment),self._evaluate(node.right,environment))
		if isinstance(node,ast.UnaryOp):
			value=self._evaluate(node.operand,environment)
			if isinstance(node.op,ast.USub):
				return -value
			if isinstance(node.op,ast.UAdd):
				return +value
			if isinstance(node.op,ast.Not):
				return not value
			if isinstance(node.op,ast.Invert):
				return ~value
		if isinstance(node,ast.BoolOp):
			if isinstance(node.op,ast.And):
				for value_node in node.values:
					if not self._evaluate(value_node,environment):
						return False
				return True
			for value_node in node.values:
				if self._evaluate(value_node,environment):
					return True
			return False
		if isinstance(node,ast.Compare):
			left=self._evaluate(node.left,environment)
			for operator,right_node in zip(node.ops,node.comparators):
				right=self._evaluate(right_node,environment)
				if not self._compare(operator,left,right):
					return False
				left=right
			return True
		if isinstance(node,ast.IfExp):
			return self._evaluate(node.body if self._evaluate(node.test,environment) else node.orelse,environment)
		if isinstance(node,ast.Call):
			assert isinstance(node.func,ast.Name)
			return self._call(node.func.id,[self._evaluate(argument,environment) for argument in node.args],environment)
		raise FormulaError(f"Formula expression is not supported: {type(node).__name__}")

	def _call(self, name: str, arguments: list[Any], environment: dict[str, Any]) -> Any:
		if name == "sensor":
			return self._sensor(arguments)
		if name == "RAW":
			if len(arguments) != 1:
				raise FormulaError("RAW requires exactly one register address")
			address=self._address(arguments[0])
			raw_value=self._read_registers(address,1)[0]
			self._reads.append(FormulaRead(address,[raw_value],"raw",1.0,0.0,"high_low","high_low",raw_value,raw_value))
			return raw_value
		if name == "range":
			if not 1 <= len(arguments) <= 3 or not all(type(argument) is int for argument in arguments):
				raise FormulaError("range requires one to three integer arguments")
			values=range(*arguments)
			if len(values) > MAX_LOOP_ITERATIONS:
				raise FormulaError(f"Formula range exceeds {MAX_LOOP_ITERATIONS} iterations")
			return values
		if name in MATH_FUNCTIONS:
			return self._math(name,arguments)
		function=environment.get(name)
		if not isinstance(function,_FormulaFunction):
			raise FormulaError(f"Formula function is undefined: {name}")
		if name in self._call_stack or len(self._call_stack) >= MAX_FUNCTION_CALL_DEPTH:
			raise FormulaError("Formula recursion is not allowed")
		parameters=function.node.args.args
		if len(parameters) != len(arguments):
			raise FormulaError(f"Formula function {name} expects {len(parameters)} arguments")
		local=dict(function.environment)
		local.update(zip((parameter.arg for parameter in parameters),arguments))
		self._call_stack.append(name)
		try:
			self._execute_statements(function.node.body,local)
		except _ReturnSignal as signal:
			return signal.value
		finally:
			self._call_stack.pop()
		raise FormulaError(f"Formula function {name} must return a value")

	def _sensor(self, arguments: list[Any]) -> int | float | str:
		if not 3 <= len(arguments) <= 6:
			raise FormulaError("sensor requires address, type, multiplier, optional offset, word order, and ASCII byte order")
		address=self._address(arguments[0])
		register_type=arguments[1]
		if register_type not in REGISTER_TYPES:
			raise FormulaError("sensor type must be uint16, int16, uint32, int32, hex, or ascii")
		if isinstance(arguments[2],bool) or not isinstance(arguments[2],(int,float)):
			raise FormulaError("sensor multiplier must be numeric")
		multiplier=float(arguments[2])
		offset=0.0
		if len(arguments) >= 4:
			if isinstance(arguments[3],bool) or not isinstance(arguments[3],(int,float)):
				raise FormulaError("sensor offset must be numeric")
			offset=float(arguments[3])
		word_order="high_low"
		if len(arguments) >= 5:
			word_order=arguments[4]
			if word_order not in {"high_low","low_high"}:
				raise FormulaError("sensor word order must be high_low or low_high")
		byte_order="high_low"
		if len(arguments) == 6:
			byte_order=arguments[5]
			if byte_order not in BYTE_ORDERS:
				raise FormulaError("sensor ASCII byte order must be high_low or low_high")
		count=2 if register_type in {"uint32","int32"} else 1
		raw_registers=self._read_registers(address,count)
		decoded=decode_registers(raw_registers,register_type,word_order,byte_order)
		value=apply_transform(decoded,multiplier,offset)
		self._reads.append(FormulaRead(address,raw_registers,register_type,multiplier,offset,word_order,byte_order,decoded,value))
		return value

	def _read_registers(self, address: int, count: int) -> list[int]:
		missing=[register for register in range(address,address+count) if register not in self._cache]
		if missing:
			self._register_read_count+=count
			if self._register_read_count > MAX_REGISTER_READS:
				raise FormulaError(f"Formula exceeds {MAX_REGISTER_READS} direct register reads")
			values=self._reader(address,count)
			if len(values) != count or any(type(value) is not int or not 0 <= value <= 65535 for value in values):
				raise FormulaError(f"Formula read returned invalid data for R{address}")
			for register,value in zip(range(address,address+count),values):
				self._cache[register]=value
		return [self._cache[register] for register in range(address,address+count)]

	def _math(self, name: str, arguments: list[Any]) -> Any:
		try:
			if name == "abs":
				return abs(self._one_argument(name,arguments))
			if name == "min":
				return min(arguments)
			if name == "max":
				return max(arguments)
			if name == "round":
				if not 1 <= len(arguments) <= 2:
					raise FormulaError("round requires one or two arguments")
				return round(*arguments)
			if name == "sqrt":
				return math.sqrt(self._one_argument(name,arguments))
			if name == "clamp":
				if len(arguments) != 3:
					raise FormulaError("clamp requires value, minimum and maximum")
				return max(arguments[1],min(arguments[0],arguments[2]))
		except (TypeError,ValueError) as error:
			raise FormulaError(f"Formula {name} arguments are invalid: {error}") from error
		raise FormulaError(f"Formula function is not allowed: {name}")

	def _one_argument(self, name: str, arguments: list[Any]) -> Any:
		if len(arguments) != 1:
			raise FormulaError(f"{name} requires exactly one argument")
		return arguments[0]

	def _binary(self, operator: ast.operator, left: Any, right: Any) -> Any:
		try:
			if isinstance(operator,ast.Add):
				return left+right
			if isinstance(operator,ast.Sub):
				return left-right
			if isinstance(operator,ast.Mult):
				return left*right
			if isinstance(operator,ast.Div):
				return left/right
			if isinstance(operator,ast.FloorDiv):
				return left//right
			if isinstance(operator,ast.Mod):
				return left%right
			if isinstance(operator,ast.Pow):
				return left**right
			if isinstance(operator,ast.BitAnd):
				return left&right
			if isinstance(operator,ast.BitOr):
				return left|right
			if isinstance(operator,ast.BitXor):
				return left^right
			if isinstance(operator,ast.LShift):
				return left << right
			if isinstance(operator,ast.RShift):
				return left >> right
		except (TypeError,ValueError,ZeroDivisionError,OverflowError) as error:
			raise FormulaError(f"Formula arithmetic failed: {error}") from error
		raise FormulaError("Formula binary operator is not allowed")

	def _compare(self, operator: ast.cmpop, left: Any, right: Any) -> bool:
		if isinstance(operator,ast.Eq):
			return left == right
		if isinstance(operator,ast.NotEq):
			return left != right
		if isinstance(operator,ast.Lt):
			return left < right
		if isinstance(operator,ast.LtE):
			return left <= right
		if isinstance(operator,ast.Gt):
			return left > right
		if isinstance(operator,ast.GtE):
			return left >= right
		if isinstance(operator,ast.In):
			return left in right
		if isinstance(operator,ast.NotIn):
			return left not in right
		if isinstance(operator,ast.Is):
			return left is right
		if isinstance(operator,ast.IsNot):
			return left is not right
		raise FormulaError("Formula comparison is not allowed")

	def _matches(self, pattern: ast.pattern, subject: Any, environment: dict[str, Any]) -> bool:
		if isinstance(pattern,ast.MatchAs):
			if pattern.name:
				environment[pattern.name]=subject
			return True
		if isinstance(pattern,ast.MatchSingleton):
			return subject is pattern.value
		if isinstance(pattern,ast.MatchValue):
			return subject == self._evaluate(pattern.value,environment)
		raise FormulaError("Formula match pattern is not supported")

	def _address(self, value: Any) -> int:
		if type(value) is not int or not 0 <= value <= 65535:
			raise FormulaError("Formula register address must be an integer from 0 to 65535")
		return value

	def _assert_local_name(self, name: str) -> None:
		if name in REGISTER_TYPES|MATH_FUNCTIONS|{"sensor","RAW","range"} or (name.startswith("R") and name[1:].isdigit()):
			raise FormulaError(f"Formula local variable name is reserved: {name}")

	def _result_value(self, value: Any) -> int | float | str | None:
		if value is None:
			return None
		if type(value) is bool:
			return int(value)
		if isinstance(value,(int,float,str)):
			return value
		raise FormulaError("Formula return value must be a number, text, or None")
