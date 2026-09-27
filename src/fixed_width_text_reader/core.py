"""Parse fixed-column-width flat files into typed records.

A fixed-width file is one where every line is divided into fields by byte
offset, not by a delimiter. These files still exist in mainframe exports,
banking feeds, and legacy reporting systems. This module turns them into
lists of dictionaries with values coerced to the types declared in a field
specification.

Design decisions
----------------

* Columns are addressed by **character index within a line**, not byte
  offset. Fixed-width files in the wild are almost always text with a single
  encoding, and reasoning about columns is far easier for humans when one
  character equals one column. If you have multibyte data where a column
  boundary falls inside a multi-byte sequence you have a harder problem than
  this library solves; decode upstream and pre-process.

* Lines shorter than the declared width are **right-padded with spaces**
  rather than rejected. Real exports routinely drop trailing blanks. A line
  longer than the declared width is truncated to the spec, because extra
  trailing characters are almost always a padding artifact or an unrelated
  trailer field the caller chose not to model.

* Records are returned as ``list[dict]`` rather than a custom class. The
  caller usually wants to feed them straight into ``csv.DictWriter`` or a
  dataclass constructor; a plain dict is the least surprising shape.

* ``None`` is returned for a field whose value is entirely whitespace, for
  every type. An empty string field and a space-padded field mean the same
  thing in a fixed-width file: no data.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import (
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    TextIO,
    Union,
)

__all__ = ["Field", "parse", "parse_file", "parse_lines"]


# A converter takes the stripped string for one column and returns the typed
# value. Returning None for blank input is handled centrally in parse(), so
# converters can assume they receive a non-blank string.
Converter = Callable[[str], object]


_BUILTIN_CONVERTERS: Dict[str, Converter] = {
    "str": lambda s: s,
    "int": lambda s: int(s),
    "float": lambda s: float(s),
    # Strip a single trailing percent sign so "12.5%" -> 12.5. We deliberately
    # do not handle leading signs or thousands separators here; if you need
    # that, pass a custom converter.
    "percent": lambda s: float(s.rstrip("%")),
}


def _resolve_converter(type_spec: Union[str, Converter]) -> Converter:
    """Return a callable converter for a type spec.

    ``type_spec`` may be a string naming a built-in converter ("str", "int",
    "float", "percent") or a callable taking the stripped string and returning
    the typed value. Resolving up front means the per-line hot path does a
    single dict lookup or direct call, never a string compare.
    """
    if callable(type_spec):
        return type_spec
    try:
        return _BUILTIN_CONVERTERS[type_spec]
    except KeyError:
        raise ValueError(
            f"Unknown type {type_spec!r}; expected one of "
            f"{sorted(_BUILTIN_CONVERTERS)} or a callable"
        ) from None


@dataclass(frozen=True)
class Field:
    """One column in a fixed-width record.

    Attributes
    ----------
    name:
        Key used in the output dict.
    start:
        Zero-based inclusive start column.
    width:
        Number of characters in the column. ``end`` is ``start + width``.
    type:
        Built-in type name or a callable ``(str) -> object``. Defaults to
        ``"str"``.
    """

    name: str
    start: int
    width: int
    type: Union[str, Converter] = "str"

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Field {self.name!r}: start must be >= 0, got {self.start}")
        if self.width <= 0:
            raise ValueError(
                f"Field {self.name!r}: width must be > 0, got {self.width}"
            )
        # Resolve eagerly so a bad type spec fails at Field construction, not
        # on the first row of data.
        _resolve_converter(self.type)

    @property
    def end(self) -> int:
        return self.start + self.width


def _iter_records(
    lines: Iterable[str], fields: Sequence[Field]
) -> Iterator[Dict[str, object]]:
    converters = [(f.name, f.start, f.end, _resolve_converter(f.type)) for f in fields]
    for raw in lines:
        # ``splitlines`` would have already stripped the newline; we only strip
        # the trailing newline characters here for the case where a caller
        # passed an iterable of un-stripped lines.
        line = raw.rstrip("\r\n")
        # Pad short lines to the furthest column end so slicing never reads
        # past the end of the string. Truncate over-long lines so a stray
        # trailer cannot leak into the last field.
        max_end = max(f.end for f in fields)
        if len(line) < max_end:
            line = line.ljust(max_end)
        elif len(line) > max_end:
            line = line[:max_end]
        record: Dict[str, object] = {}
        for name, start, end, convert in converters:
            piece = line[start:end]
            stripped = piece.strip()
            if stripped == "":
                record[name] = None
            else:
                record[name] = convert(stripped)
        yield record


def parse_lines(
    lines: Iterable[str], fields: Sequence[Field]
) -> List[Dict[str, object]]:
    """Parse an iterable of lines into a list of record dicts.

    Newline characters are stripped from each line; you can pass either
    already-split lines or a file object. Blank lines (empty or whitespace
    only) are skipped, because fixed-width exports frequently contain them
    between batches.
    """
    if not fields:
        raise ValueError("fields must contain at least one Field")
    out: List[Dict[str, object]] = []
    for raw in lines:
        if raw.strip() == "":
            continue
        out.extend(_iter_records([raw], fields))
    return out


def parse(text: str, fields: Sequence[Field]) -> List[Dict[str, object]]:
    """Parse a single string containing zero or more newline-separated records."""
    return parse_lines(text.splitlines(), fields)


def parse_file(
    source: Union[str, "os.PathLike[str]", TextIO],
    fields: Sequence[Field],
    *,
    encoding: str = "utf-8",
) -> List[Dict[str, object]]:
    """Parse a fixed-width file.

    ``source`` may be a path or an already-open text-mode file object. When a
    path is given the file is opened with the given ``encoding`` and closed
    here. When a file object is given the caller owns its lifetime.
    """
    if hasattr(source, "read"):
        return parse_lines(source, fields)
    # ``source`` is a path. Open with newline="" so the file's own line endings
    # are preserved and splitlines() in parse() handles \r\n, \r, and \n
    # uniformly. We do not use universal newline translation here because it
    # would turn \r\n into \n before we ever see it, which is fine, but newline=""
    # keeps the behaviour explicit and identical across platforms.
    with open(source, "r", encoding=encoding, newline="") as fh:  # type: ignore[arg-type]
        return parse_lines(fh, fields)
