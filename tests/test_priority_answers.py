import unittest

from x68k_knowledge.quality import validate


def answer(text, page):
    return dict(mode='answer', paragraphs=[dict(text=text, citations=[1])],
                tables=[], sources=[dict(source_id='inside-x68000', pdf_page=page)])


class AnswerQualityGateTests(unittest.TestCase):
    def test_repeated_bit_prefixes_are_valid_but_wrong_range_is_rejected(self):
        validate('crtc-sync', answer('R20 $E80028 bit8〜bit10 と R0 $E82400 bit0〜bit2。', 237))
        with self.assertRaises(AssertionError):
            validate('crtc-sync', answer('R20 $E80028 bit0〜bit7 と R0 $E82400 bit0〜bit2。', 237))

    def test_japanese_negative_gcr_and_wrong_address(self):
        text = 'MTC $E8408A、MAR $E8408C、DAR $E84094。GCR $E840FF はチャンネル0にはありません。'
        validate('dmac-addresses', answer(text, 33))
        with self.assertRaises(AssertionError):
            validate('dmac-addresses', answer(text.replace('E8408A', 'E84080'), 33))

    def test_uncertainty_does_not_excuse_wrong_upper_bit_description(self):
        validate('unresolved-bits', answer('取り込み注釈のSIZ/COLは未確定。同期対象はR20のbit8〜10。', 237))
        validate('unresolved-bits', answer('構造化注記ではSIZ/COLは未確認。', 237))
        with self.assertRaises(AssertionError):
            validate('unresolved-bits', answer('取り込み注釈のSIZ/COLは未確定。R20の上位3ビットとR0を同期する。', 237))
