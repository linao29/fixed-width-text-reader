# fixed-width-text-reader

Parses fixed-column-width flat files into a list of typed dicts using a field specification. Standard library only.

```python
from fixed_width_text_reader import Field, parse, parse_file, parse_lines

fields = [
    Field(name="id", start=0, width=4, type="int"),
    Field(name="name", start=4, width=10),
    Field(name="rate", start=14, width=6, type="float"),
]

records = parse("0001Alice      12.50\n0002Bob         9.99\n", fields)
# [{'id': 1, 'name': 'Alice', 'rate': 12.5},
#  {'id': 2, 'name': 'Bob', 'rate': 9.99}]

# Or from any iterable of lines:
records = parse_lines(["0001Alice      12.50", "0002Bob         9.99"], fields)

# Or from a file path / open text file object:
# records = parse_file("data.txt", fields, encoding="utf-8")
```

## Why this exists

Mainframe exports, banking feeds, and legacy reports still arrive as fixed-width text. The usual workaround is a pile of `line[0:4]` slices scattered through a script. This library replaces that with a declared field spec so the mapping lives in one place and values come out already typed.

The trade-off is simplicity over flexibility. There is no schema inference, no automatic detection of column widths from a header row, and no support for multi-line records. You tell it the columns and it reads them.

## Exports

- `Field(name, start, width, type="str")` — describes one column. `start` is a zero-based character index; `width` is the character count. `type` is one of `"str"`, `"int"`, `"float"`, `"percent"` (strips a trailing `%`), or a callable `(str) -> object`.
- `parse(text, fields)` — parse a string containing newline-separated records.
- `parse_lines(lines, fields)` — parse an iterable of lines.
- `parse_file(source, fields, *, encoding="utf-8")` — parse a path or an open text-mode file object.

## Edge cases you will hit

- **Short lines are right-padded with spaces.** A line that does not reach the last column is treated as if the missing columns were blank. Whitespace-only fields become `None`.
- **Long lines are truncated** to the end of the last declared field. Trailing characters you did not model are dropped silently.
- **Blank lines are skipped.** A line that is empty or whitespace-only does not produce a record.
- **Columns are character-based, not byte-based.** If your file contains multi-byte characters and a column boundary falls inside one, this library will not handle it correctly; decode and pre-process first.
- **Conversion errors are not caught.** If a column declared `int` contains `"abc"`, the `ValueError` from `int()` propagates to the caller.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

