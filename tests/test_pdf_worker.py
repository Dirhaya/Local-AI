import io
import unittest
from pypdf import PdfWriter
from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
from app.pdf_worker import extract
def pdf(encrypted=False):
 w=PdfWriter();p=w.add_blank_page(width=600,height=800)
 font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
 p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
 stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 700 Td (Eigenvalues describe a square matrix. Study chapter three, section two.) Tj ET')
 p[NameObject('/Contents')]=w._add_object(stream)
 if encrypted:w.encrypt('password')
 out=io.BytesIO();w.write(out);return out.getvalue()
class PDFTests(unittest.TestCase):
 def test_real_text_and_page(self):
  r=extract(pdf());self.assertEqual(r['pages'][0]['page'],1);self.assertIn('Eigenvalues',r['pages'][0]['text'])
 def test_invalid_magic(self):
  with self.assertRaises(ValueError):extract(b'<html>not a PDF</html>')
 def test_encrypted_pdf(self):
  with self.assertRaisesRegex(ValueError,'password protected'):extract(pdf(True))
 def test_empty_scanned(self):
  w=PdfWriter();w.add_blank_page(width=100,height=100);out=io.BytesIO();w.write(out)
  with self.assertRaisesRegex(ValueError,'OCR'):extract(out.getvalue())
 def test_page_limit(self):
  w=PdfWriter()
  for _ in range(501):w.add_blank_page(width=100,height=100)
  out=io.BytesIO();w.write(out)
  with self.assertRaisesRegex(ValueError,'500 pages'):extract(out.getvalue())
if __name__=='__main__':unittest.main()
