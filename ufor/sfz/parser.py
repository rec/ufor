"""Lossless SFZ text parsing and metadata inspection."""

import json
import re
from pathlib import PurePosixPath

from pydantic import ValidationError

from ..assets import RelativeFileLocation
from .model import (
    InstrumentMetadata,
    ParsedOpcode,
    ParsedRegion,
    SfzLocation,
    SfzSource,
    SlotMetadata,
    UnimplementedFeature,
)
from .registry import (
    AMP_VELOCITY_CURVE,
    OPCODE_ALIASES,
    PARSABLE_OPCODES,
    Support,
    diagnostic_reason,
    header_support,
)


def parse(text: str) -> SfzSource:
    """Parse SFZ text without opening files or invoking vendor preprocessors."""
    metadata, slots, metadata_issues = _metadata(text)
    regions, issues = _parse(text)
    if not regions and not issues:
        raise ValueError('SFZ file contains no regions')
    return SfzSource(
        regions=regions,
        instrument_metadata=metadata or {},
        slot_metadata=slots,
        unimplemented=[*issues, *metadata_issues],
    )


def sample_paths(source: SfzSource) -> list[str]:
    """Return unique portable file references for the caller to inspect and seal."""
    result: list[str] = []
    for index, region in enumerate(source.regions, 1):
        samples = [o.value for o in region.opcodes if o.opcode == 'sample']
        if not samples:
            raise ValueError(f'Region {index}: sample is required')
        if samples[-1].startswith('*'):
            continue
        path = str(
            PurePosixPath(region.default_path.replace('\\', '/'))
            / samples[-1].replace('\\', '/')
        )
        RelativeFileLocation(path=path)
        if path not in result:
            result.append(path)
    return result


def _metadata(
    text: str,
) -> tuple[
    dict[str, object] | None, dict[int, dict[str, object]], list[UnimplementedFeature]
]:
    instrument: dict[str, object] | None = None
    slots: dict[int, dict[str, object]] = {}
    issues: list[UnimplementedFeature] = []
    pending: tuple[dict[str, object], int] | None = None
    region = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        match = RECS_METADATA.fullmatch(stripped)
        if stripped.startswith(('// recs:instrument', '// recs:slot')) and not match:
            raise ValueError(f'Malformed recs metadata on line {line_number}')
        if match:
            kind, value = match.groups()
            try:
                data = json.loads(value)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f'Malformed recs {kind} metadata on line {line_number}: {e}'
                ) from None
            if kind == 'instrument':
                if not isinstance(data, dict):
                    raise ValueError('Recs instrument metadata must be a JSON object')
                if data.get('version') != 2:
                    issues.append(
                        UnimplementedFeature(
                            location=SfzLocation(
                                header='recs',
                                opcode='instrument',
                                line=line_number,
                                column=line.index('//') + 1,
                            ),
                            value=str(data.get('version')),
                            reason='Recs SFZ metadata version is not implemented',
                        )
                    )
                    continue
                try:
                    parsed = InstrumentMetadata.model_validate(data)
                except ValidationError as e:
                    raise ValueError(
                        f'Malformed recs instrument metadata: {e}'
                    ) from None
                instrument = parsed.model_dump(exclude={'version'})
            else:
                if not isinstance(data, dict):
                    raise ValueError('Recs slot metadata must be a JSON object')
                try:
                    pending = (
                        SlotMetadata.model_validate(data).model_dump(),
                        line_number,
                    )
                except ValidationError as e:
                    raise ValueError(f'Malformed recs slot metadata: {e}') from None
            continue
        if not stripped or stripped.startswith('//'):
            continue
        if '<region>' in stripped:
            region += stripped.count('<region>')
            if pending is not None:
                slots[region] = pending[0]
                pending = None
        elif pending is not None:
            raise ValueError(
                f'Recs slot metadata on line {pending[1]} must precede a region'
            )
    if pending is not None:
        raise ValueError(f'Recs slot metadata on line {pending[1]} has no region')
    return instrument, slots, issues


def _sfz_issue_position(feature: UnimplementedFeature) -> tuple[int, int]:
    assert isinstance(feature.location, SfzLocation)
    return feature.location.line, feature.location.column


def _parse(text: str) -> tuple[list[ParsedRegion], list[UnimplementedFeature]]:
    unimplemented: list[UnimplementedFeature] = []
    text = BLOCK_COMMENT.sub(_blank_comment, text)
    text = LINE_COMMENT.sub('', text)
    text, definitions = _remove_preprocessors(text, unimplemented)

    matches = list(TOKEN.finditer(text))
    if not matches and text.strip():
        raise ValueError('SFZ file contains no headers or opcodes')

    current: str | None = None
    current_line = 0
    default_path = ''
    global_opcodes: list[ParsedOpcode] = []
    master_opcodes: list[ParsedOpcode] = []
    group_opcodes: list[ParsedOpcode] = []
    region_opcodes: list[ParsedOpcode] = []
    regions: list[ParsedRegion] = []
    variables: dict[str, str] = {}
    next_definition = 0

    def finish_region() -> None:
        if current == 'region':
            regions.append(
                ParsedRegion(
                    default_path=default_path,
                    opcodes=[
                        *global_opcodes,
                        *master_opcodes,
                        *group_opcodes,
                        *region_opcodes,
                    ],
                    line=current_line,
                )
            )

    line = 1
    previous = 0
    for i, match in enumerate(matches):
        line += text[previous : match.start()].count('\n')
        previous = match.start()
        while (
            next_definition < len(definitions)
            and definitions[next_definition][0] < line
        ):
            _, name, value = definitions[next_definition]
            variables[name] = value
            next_definition += 1
        column = match.start() - text.rfind('\n', 0, match.start())
        if i == 0 and text[: match.start()].strip():
            raise ValueError('Unexpected text before first SFZ header')
        header, opcode = match.groups()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if header is not None:
            if text[match.end() : end].strip():
                raise ValueError(f'Unexpected text after <{header}>')
            finish_region()
            current = header.lower()
            current_line = line
            if header_support(current) != Support.supported:
                unimplemented.append(
                    UnimplementedFeature(
                        location=SfzLocation(
                            header=current,
                            opcode=None,
                            line=line,
                            column=column,
                        ),
                        value=None,
                        reason=diagnostic_reason(current, header=True),
                    )
                )
                continue
            if current == 'global':
                global_opcodes = []
                master_opcodes = []
                group_opcodes = []
            elif current == 'master':
                master_opcodes = []
                group_opcodes = []
            elif current == 'group':
                group_opcodes = []
            elif current == 'region':
                region_opcodes = []
            continue

        if current is None:
            raise ValueError(f'SFZ opcode outside a header: {opcode}')
        value = _expand_variables(text[match.end() : end].strip(), variables, line)
        name = opcode.lower()
        item = ParsedOpcode(
            header=current,
            opcode=name,
            value=value,
            line=line,
            column=column,
        )
        if header_support(current) != Support.supported:
            _add_unimplemented(
                unimplemented,
                item,
                diagnostic_reason(name),
            )
            continue
        if not value and not (current == 'control' and name == 'default_path'):
            raise ValueError(f'SFZ opcode has no value: {opcode}')
        canonical = OPCODE_ALIASES.get(name, name)
        supported = canonical in PARSABLE_OPCODES or AMP_VELOCITY_CURVE.fullmatch(
            canonical
        )
        if current == 'control':
            if name != 'default_path':
                _add_unimplemented(unimplemented, item, diagnostic_reason(name))
                continue
            default_path = value
        elif not supported:
            _add_unimplemented(unimplemented, item, diagnostic_reason(name))
        elif current == 'global':
            global_opcodes.append(item)
        elif current == 'master':
            master_opcodes.append(item)
        elif current == 'group':
            group_opcodes.append(item)
        else:
            region_opcodes.append(item)

    finish_region()
    return regions, unimplemented


def _add_unimplemented(
    features: list[UnimplementedFeature], item: ParsedOpcode, reason: str
) -> None:
    features.append(
        UnimplementedFeature(
            location=SfzLocation(
                header=item.header,
                opcode=item.opcode,
                line=item.line,
                column=item.column,
            ),
            value=item.value,
            reason=reason,
        )
    )


def _blank_comment(match: re.Match[str]) -> str:
    return ''.join('\n' if c == '\n' else ' ' for c in match.group())


def _remove_preprocessors(
    text: str, unimplemented: list[UnimplementedFeature]
) -> tuple[str, list[tuple[int, str, str]]]:
    result: list[str] = []
    definitions: list[tuple[int, str, str]] = []
    for line, content in enumerate(text.splitlines(keepends=True), 1):
        stripped = content.lstrip()
        if not stripped.startswith('#'):
            result.append(content)
            continue
        body = stripped[1:].strip()
        parts = body.split(maxsplit=1)
        directive = parts[0] if parts else ''
        value = parts[1] if len(parts) == 2 else ''
        opcode = f'#{directive}' if directive else '#'
        if directive == 'define':
            match = DEFINE.fullmatch(value.strip())
            if match is None:
                raise ValueError(f'Malformed SFZ #define on line {line}')
            definitions.append((line, match.group(1), match.group(2)))
            result.append('\n' if content.endswith('\n') else '')
            continue
        if directive == 'include':
            reason = 'Vendor-specific #include preprocessing is not implemented'
        else:
            reason = 'SFZ preprocessing directive is not implemented'
        unimplemented.append(
            UnimplementedFeature(
                location=SfzLocation(
                    header='preprocessor',
                    opcode=opcode,
                    line=line,
                    column=len(content) - len(stripped) + 1,
                ),
                value=value or None,
                reason=reason,
            )
        )
        result.append('\n' if content.endswith('\n') else '')
    return ''.join(result), definitions


def _expand_variables(value: str, variables: dict[str, str], line: int) -> str:
    def expand(text: str, pending: tuple[str, ...]) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group()
            if name not in variables:
                raise ValueError(f'Undefined SFZ variable {name} on line {line}')
            if name in pending:
                raise ValueError(f'Recursive SFZ variable {name} on line {line}')
            return expand(variables[name], (*pending, name))

        return VARIABLE.sub(replace, text)

    return expand(value, ())


NOTES = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
NOTE = re.compile(r'([A-Ga-g])([#b]?)(-?\d+)')
TOKEN = re.compile(r'<([A-Za-z_][A-Za-z0-9_]*)>|([A-Za-z_][A-Za-z0-9_]*)=')
BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
LINE_COMMENT = re.compile(r'//.*$', re.MULTILINE)
PREPROCESSOR = re.compile(r'^\s*#', re.MULTILINE)
DEFINE = re.compile(r'(\$[A-Za-z_][A-Za-z0-9_]*)\s+(.+)')
VARIABLE = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')
RECS_METADATA = re.compile(r'//\s*recs:(instrument|slot)\s+(\{.*\})')
