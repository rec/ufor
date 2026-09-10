import json
from hashlib import sha256
from pathlib import Path

import pytest

from ufor.vl70 import VL70Patch, parse_vl70


@pytest.fixture
def patch() -> VL70Patch:
    case = json.loads((Path(__file__).parents[1] / 'conformance/vl70.json').read_text())
    data = (
        bytes.fromhex(case['prefix_hex'])
        + case['title_ascii'].encode('ascii')
        + bytes(case['zero_payload_bytes'])
        + bytes.fromhex(case['suffix_hex'])
    )
    assert sha256(data).hexdigest() == case['sha256']
    return VL70Patch(data=data)


def test_relocation_matches_portable_vector_and_is_reversible(patch: VL70Patch) -> None:
    case = json.loads(
        (Path(__file__).parents[1] / 'conformance/vl70.json').read_text()
    )['relocation']
    result = patch.relocate(case['slot'], case['device_number'])
    assert result.slot == 7
    assert result.device_number == 1
    assert result.title == 'UFORTST '
    assert result.data[172] == case['checksum']
    assert sha256(result.data).hexdigest() == case['sha256']
    assert [i for i in range(174) if result.data[i] != patch.data[i]] == case[
        'changed_offsets'
    ]
    assert result.relocate(0, 0) == patch


def test_duplicate_occurrences_and_opaque_spans_round_trip(patch: VL70Patch) -> None:
    spans = [
        b'padding',
        patch.data,
        b'\xf0\x01\xf7',
        patch.data,
        b'\xf0broken',
        patch.data,
        b'tail\xf7',
    ]
    data = b''.join(spans)
    entries = parse_vl70(data)
    assert [i.data for i in entries] == spans
    assert b''.join(i.data for i in entries) == data
    assert [i.offset for i in entries] == [
        sum(len(j) for j in spans[:i]) for i in range(len(spans))
    ]
    assert [i.patch is not None for i in entries] == [
        False,
        True,
        False,
        True,
        False,
        True,
        False,
    ]
    assert all(i.diagnostic for i in entries if i.patch is None)
    assert parse_vl70(b'') == []


def test_large_library_retains_repeated_slots(patch: VL70Patch) -> None:
    data = b''.join(patch.relocate(i % 64).data for i in range(128))
    entries = parse_vl70(data)
    assert len(entries) == 128
    assert b''.join(i.data for i in entries) == data
    assert entries[0].patch == entries[64].patch
    assert entries[0].offset != entries[64].offset


def test_repeated_selection_does_not_mutate_original(patch: VL70Patch) -> None:
    first = patch.relocate(0, 15)
    second = patch.relocate(63)
    assert first.device_number == 15
    assert first.data[3:] == patch.data[3:]
    assert second.slot == 63
    assert second.device_number == patch.device_number == 0
    assert patch.slot == first.slot == 0
    assert second.data[9:172] == patch.data[9:172]
    assert sum(second.data[4:173]) % 128 == 0


@pytest.mark.parametrize('value', [-1, 64, 1.5, True, '7', None])
def test_invalid_slots_are_rejected(patch: VL70Patch, value: object) -> None:
    with pytest.raises(ValueError, match='slot must'):
        patch.relocate(value)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize('value', [-1, 16, 1.5, False, '1'])
def test_invalid_devices_are_rejected(patch: VL70Patch, value: object) -> None:
    with pytest.raises(ValueError, match='device number must'):
        patch.relocate(0, value)  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    'offset,value,diagnostic',
    [
        (0, 0, 'framing'),
        (173, 0, 'framing'),
        (20, 128, 'seven-bit'),
        (1, 1, 'header'),
        (2, 16, 'header'),
        (3, 0, 'header'),
        (4, 0, 'count'),
        (6, 0, 'address'),
        (8, 64, 'source slot'),
        (172, 0, 'checksum'),
    ],
)
def test_uneditable_messages_remain_available(
    patch: VL70Patch, offset: int, value: int, diagnostic: str
) -> None:
    data = bytearray(patch.data)
    data[offset] = value
    original = bytes(data)
    with pytest.raises(ValueError, match=diagnostic):
        VL70Patch(data=original)
    entries = parse_vl70(original)
    assert b''.join(i.data for i in entries) == original
    assert all(i.patch is None for i in entries)
    assert any(diagnostic in (i.diagnostic or '') for i in entries)


def test_unknown_payload_and_title_bytes_are_preserved(patch: VL70Patch) -> None:
    data = bytearray(patch.data)
    data[9] = 0
    data[17:172] = bytes(i % 128 for i in range(155))
    data[172] = -sum(data[4:172]) % 128
    original = VL70Patch(data=bytes(data))
    result = original.relocate(7)
    assert result.data[9:172] == original.data[9:172]
    assert result.title == '\x00FORTST '
    assert sum(result.data[4:173]) % 128 == 0


def test_unfamiliar_message_length_stays_opaque() -> None:
    data = b'\xf0\x43\xf7'
    entry = parse_vl70(data)[0]
    assert entry.data == data
    assert entry.patch is None
    assert 'length' in (entry.diagnostic or '')
