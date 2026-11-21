"""Deterministic checks of cited technical claims; no model/API calls on import."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    question: str
    pages: tuple[int, ...]
    source_id: str = 'inside-x68000'


CASES = {
    'screen-modes': Case('対応している画面モードは？', (171,)),
    'crtc-sync': Case('CRTC R20のアドレスと、ビデオコントローラR0と一致させるビット範囲は？', (237, 238)),
    'video-color-code': Case('ビデオコントローラR0のCOLフィールドの2進10と11は、それぞれ何色のモードですか？', (238,)),
    'dmac-addresses': Case('DMACチャンネル2のMTC、MAR、DARのアドレスは？ GCRはチャンネル0にもありますか？', (33,)),
    'unresolved-bits': Case('CRTC R20のSIZとCOLの個別ビット番号は、今回の取り込み注釈から確定できますか？', (237,)),
    'unsupported-color-mode': Case('768×512で256色は表示できますか？', (171,)),
    'virtual-screen-size': Case('256×256で16色4ページのとき、実画面の大きさは？', (171,)),
}


class QualityError(AssertionError):
    """An explicit exception so checks remain active under python -O."""


def require(condition, message):
    if not condition:
        raise QualityError(message)


def norm(value):
    value = unicodedata.normalize('NFKC', value).replace('−', '-').replace('–', '-')
    value = re.sub(r'(?<=\d),(?=\d)', '', value)
    value = re.sub(r'(?<=\d)\s*[xXｘ]\s*(?=\d)', '×', value)
    return value.replace('**', '').replace('`', '')


def _negative(text):
    return bool(re.search(r'いいえ|未定義|未対応|非対応|不可|なし|ありません|ない|not\s+(?:supported|available)|no\b|×', text, re.I))


def _interlaced(text):
    text = re.sub(r'ノン[-\s]*インターレース|非インターレース|インターレース(?:なし|ではない|ではありません)', '', text)
    return 'インターレース' in text


def _contract(answer, case):
    require(isinstance(answer, dict) and answer.get('mode') == 'answer', 'Answer generation did not complete')
    sources = answer.get('sources')
    require(isinstance(sources, list) and sources, 'Missing sources')
    paragraphs, tables = answer.get('paragraphs', []), answer.get('tables', [])
    require(isinstance(paragraphs, list) and isinstance(tables, list) and bool(paragraphs or tables), 'Empty answer')
    all_blocks, grounded = [], []
    for kind, blocks in [('paragraph', paragraphs), ('table', tables)]:
        for block in blocks:
            require(isinstance(block, dict), 'Malformed answer block')
            citations = block.get('citations')
            require(isinstance(citations, list) and citations, 'Uncited answer block')
            require(all(type(i) is int and 1 <= i <= len(sources) for i in citations), 'Invalid citation number')
            if kind == 'paragraph':
                require(isinstance(block.get('text'), str) and bool(block['text'].strip()), 'Empty paragraph')
                text = block['text']
            else:
                columns, rows = block.get('columns'), block.get('rows')
                require(isinstance(columns, list) and len(columns) >= 2 and all(isinstance(c, str) for c in columns), 'Malformed table columns')
                require(isinstance(rows, list) and rows, 'Empty table')
                require(all(isinstance(row, list) and len(row) == len(columns) and all(isinstance(c, str) for c in row) for row in rows), 'Misaligned table cells')
                text = '\n'.join(' / '.join(row) for row in rows)
            entry = (kind, block, norm(text))
            all_blocks.append(entry)
            if any(isinstance(sources[i - 1], dict) and sources[i - 1].get('source_id') == case.source_id and sources[i - 1].get('pdf_page') in case.pages for i in citations):
                grounded.append(entry)
    require(grounded, 'Required source page is not cited by the answer')
    return all_blocks, grounded


def _units(blocks):
    for kind, block, text in blocks:
        if kind == 'table':
            for row in block['rows']:
                yield norm(' / '.join(row))
        else:
            yield text


def _entity_claims(blocks, pattern):
    """Keep values tied to the register naming them, including table rows."""
    for text in _units(blocks):
        matches = list(re.finditer(pattern, text, re.I))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            yield match.group().upper(), text[match.end():end]


def _range(text, lo, hi):
    return bool(re.search(rf'{lo}\s*[〜～~\-:]\s*(?:bit|ビット)?\s*{hi}|{hi}\s*:\s*{lo}|{lo}[、,，・\s]+{lo+1}[、,，・\s]+{hi}', text, re.I))


def _crtc(blocks, all_blocks):
    facts = {'R20': set(), 'R0': set()}
    for name, text in _entity_claims(blocks, r'R20|R0'):
        address, lo, hi = ('$E80028', 8, 10) if name == 'R20' else ('$E82400', 0, 2)
        if address[1:] in text.upper():
            facts[name].add('address')
        if _range(text, lo, hi):
            facts[name].add('bits')
    require(all(v == {'address', 'bits'} for v in facts.values()), 'Wrong/missing register address or associated synchronization range')
    for name, text in _entity_claims(all_blocks, r'R20|R0'):
        wrong = ('E80020', 'E82400') if name == 'R20' else ('E02400', 'E80028')
        for address in wrong:
            if address in text.upper():
                require(bool(re.search(r'誤|ではな|ありません', text)), 'Contradictory register address')
        if name == 'R20' and _range(text, 0, 7):
            require(bool(re.search(r'ではな|誤|ありません', text)), 'R20 bit0..7 incorrectly asserted as synchronized')
        if name == 'R20' and _range(text, 0, 2):
            require(bool(re.search(r'ではな|誤|ありません', text)), 'R20 and R0 ranges swapped')
        if name == 'R0' and _range(text, 8, 10):
            require(bool(re.search(r'ではな|誤|ありません', text)), 'R0 and R20 ranges swapped')


def _colors(blocks, all_blocks):
    found = set()
    for text in _units(blocks):
        matches = list(re.finditer(r'(?<![\d])(?:10|11)(?![\d])', text))
        for i, match in enumerate(matches):
            segment = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
            if match.group() == '10' and '未定義' in segment:
                found.add('10')
            if match.group() == '11' and '65536' in segment:
                found.add('11')
    require(found == {'10', '11'}, 'COL codes must map 10 to undefined and 11 to 65536 colors')
    for text in _units(all_blocks):
        if re.search(r'(?<!\d)10(?!\d)[^。\n]{0,35}65536', text):
            require('11' in text or _negative(text), 'Undefined COL=10 mapped to 65536 colors')


def _dmac(blocks, all_blocks):
    expected = {'MTC': 'E8408A', 'MAR': 'E8408C', 'DAR': 'E84094', 'GCR': 'E840FF'}
    found = set()
    for name, text in _entity_claims(blocks, r'MTC|MAR|DAR|GCR'):
        if expected[name] in text.upper():
            found.add(name)
    require(found == set(expected), 'Wrong/missing addresses associated with DMAC registers')
    for name, text in _entity_claims(all_blocks, r'MTC|MAR|DAR|GCR'):
        for match in re.finditer(r'(?:\$|0x)(E840[0-9A-F]{2})\b', text, re.I):
            if re.search(r'基底|ベース', text[max(0, match.start()-10):match.start()]):
                continue
            require(match[1].upper() == expected[name] or bool(re.search(r'誤|ではな', text)), 'Contradictory DMAC register address')
    absent = False
    for text in _units(all_blocks):
        if 'GCR' in text.upper() and re.search(r'(?:チャンネル|チャネル|ch)\s*#?\s*0', text, re.I):
            require(_negative(text), 'GCR incorrectly present on channel0')
    for text in _units(blocks):
        if 'GCR' in text.upper() and re.search(r'(?:チャンネル|チャネル|ch)\s*#?\s*0', text, re.I) and _negative(text):
            absent = True
    require(absent, 'Missing channel0 GCR exception')


def _unresolved(blocks, all_blocks):
    text = '\n'.join(_units(blocks))
    require(any(t in text for t in ['未確定', '未確認', '確定でき', '断定でき', '不整合']), 'Missing unresolved annotation scope')
    require(any(t in text for t in ['注釈', '取り込み', '構造化注記']), 'Annotation scope attributed to the book')
    for body in _units(all_blocks):
        if re.search(r'R20\s*の?\s*上位3ビット', body, re.I):
            require(any(t in body for t in ['上位3ビットではない', '上位3ビットではありません']), 'R20 bit8..10 called uppermost three bits')


def _virtual_configurations(blocks):
    configurations = set()
    for kind, block, _ in blocks:
        if kind != 'table':
            continue
        columns = [norm(c) for c in block['columns']]
        virtual = next((i for i, c in enumerate(columns) if any(k in c for k in ['実画面', 'VRAM', '仮想']) and '表示' not in c), None)
        colors = next((i for i, c in enumerate(columns) if '色' in c), None)
        pages = next((i for i, c in enumerate(columns) if 'ページ' in c), None)
        if None not in (virtual, colors, pages):
            for row in block['rows']:
                dimensions = re.findall(r'\d+\s*×\s*\d+', norm(row[virtual]))
                color, page = re.search(r'\d+', norm(row[colors])), re.search(r'\d+', norm(row[pages]))
                require(len(set(dimensions)) == 1 and color is not None and page is not None, 'Ambiguous VRAM configuration row')
                configurations.add((dimensions[0].replace(' ', ''), int(color[0]), int(page[0])))
    return configurations


def _screen(blocks, all_blocks):
    expected = {('1024×1024', 16, 1), ('512×512', 65536, 1), ('512×512', 256, 2), ('512×512', 16, 4)}
    require(expected <= _virtual_configurations(blocks), 'Incorrect/missing VRAM/color/page relationships')
    require(_virtual_configurations(all_blocks) <= expected, 'Contradictory VRAM/color/page relationship')
    text = '\n'.join(_units(blocks))
    require(all(v in text.replace(' ', '') for v in ['768×512', '512×512', '512×256', '256×256']), 'Missing display resolutions')
    require('31' in text and '15' in text and 'インターレース' in text, 'Missing scan conditions')
    unsupported = False
    for kind, block, _ in all_blocks:
        if kind != 'table':
            continue
        columns = [norm(c) for c in block['columns']]
        frequency = next((i for i, c in enumerate(columns) if '周波数' in c or '走査条件' in c), None)
        software = next((i for i, c in enumerate(columns) if any(k in c for k in ['ソフト', 'IOCS'])), None)
        for row in block['rows']:
            cells = [norm(c) for c in row]
            if cells[0].replace(' ', '') == '512×256':
                candidates = [cells[software]] if software is not None else [cells[i] for i,c in enumerate(columns) if '31' in c or '15' in c]
                for value in candidates:
                    require(_negative(value) or '○' in value or '◯' in value, '512×256 incorrectly software-supported')
                    unsupported = True
            if cells[0].replace(' ', '') == '512×512':
                if frequency is not None and '31' in cells[frequency]:
                    require(not _interlaced(' '.join(cells)), '31kHz 512×512 incorrectly interlaced')
                for i, column in enumerate(columns):
                    if '31' in column:
                        require(not _interlaced(cells[i]), '31kHz 512×512 incorrectly interlaced')
    require(unsupported, 'Missing explicit software limitation for 512×256')


def _unsupported_color(blocks, all_blocks):
    text = '\n'.join(_units(blocks))
    require('768×512' in text and '256' in text and _negative(text), 'Missing unsupported 768×512/256-color conclusion')
    for body in _units(all_blocks):
        if re.search(r'768×512[^。\n]{0,25}256色[^。\n]{0,25}(?:できます|可能です|対応しています)', body):
            require(_negative(body), 'Unsupported 768×512/256-color combination asserted')


def _virtual_size(blocks, all_blocks):
    found = False
    for group in [all_blocks, blocks]:
        for kind, block, text in group:
            if kind == 'table':
                pairs = [(norm(row[0]), norm(row[1])) for row in block['rows'] if len(row) == 2]
            else:
                pairs = [('実画面', m[1]) for m in re.finditer(r'実画面(?:[（(][^）)]*[）)])?[^。\n]{0,25}?(\d+×\d+)', text)]
            for label, value in pairs:
                if any(k in label for k in ['実画面', 'VRAM', '仮想']) and '表示' not in label:
                    require('512×512' in value and '256×256' not in value, 'Display size confused with virtual-screen size')
                    if group is blocks:
                        found = True
    require(found, 'Missing cited virtual-screen size')


def validate(case_id, answer):
    require(case_id in CASES, f'Unknown quality case: {case_id}')
    all_blocks, grounded = _contract(answer, CASES[case_id])
    validators = {
        'screen-modes': _screen, 'crtc-sync': _crtc, 'video-color-code': _colors,
        'dmac-addresses': _dmac, 'unresolved-bits': _unresolved,
        'unsupported-color-mode': _unsupported_color, 'virtual-screen-size': _virtual_size,
    }
    validators[case_id](grounded, all_blocks)
