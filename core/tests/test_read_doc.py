# -*- coding: utf-8 -*-
"""read_doc：OCR 沒安裝要明說，不能講成「解析度不足」讓主人去重拍。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import read_doc as rd  # noqa: E402


class OcrNotInstalled(unittest.TestCase):
    def setUp(self):
        self.orig = rd.OCR_BIN
        rd.OCR_BIN = os.path.join(tempfile.gettempdir(), "no-such-ocr-bin")

    def tearDown(self):
        rd.OCR_BIN = self.orig

    def test_image_says_ocr_not_installed(self):
        msg = rd.read_image("/tmp/whatever.png")
        self.assertIn("OCR 未安裝", msg)
        self.assertNotIn("解析度", msg)


if __name__ == "__main__":
    unittest.main()
