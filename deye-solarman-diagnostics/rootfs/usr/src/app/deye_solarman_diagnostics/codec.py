from __future__ import annotations


def combine_words(registers: list[int], word_order: str) -> list[int]:
	if len(registers) <= 1:
		return registers
	if word_order == "low_high":
		return list(reversed(registers))
	return registers


def decode_registers(registers: list[int], register_type: str, word_order: str) -> int | str:
	ordered=combine_words(registers, word_order)
	if register_type == "hex":
		return " ".join(f"0x{value:04X}" for value in ordered)
	if register_type == "uint16":
		return ordered[0]
	if register_type == "int16":
		value=ordered[0]
		return value-65536 if value >= 32768 else value
	if register_type in {"uint32","int32"}:
		value=(ordered[0] << 16)|ordered[1]
		if register_type == "int32" and value >= 2147483648:
			return value-4294967296
		return value
	raise ValueError(f"Unsupported register type: {register_type}")


def apply_transform(decoded_value: int | str, multiplier: float, offset: float) -> int | float | str:
	if isinstance(decoded_value, str):
		return decoded_value
	value=decoded_value*multiplier+offset
	if value.is_integer():
		return int(value)
	return round(value,6)
