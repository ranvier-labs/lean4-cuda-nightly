from __future__ import annotations

import unittest

from scripts.highlight_lean import highlight_block, highlight_lean


class HighlightLeanTests(unittest.TestCase):
    def test_keywords_attributes_and_comments(self) -> None:
        html = highlight_lean(
            "@[cuda_kernel]\ndef saxpy : Cuda.DeviceM Unit := do\n  -- load\n  let x := 1\n"
        )
        self.assertIn('<span class="at">@[cuda_kernel]</span>', html)
        self.assertIn('<span class="kw">def</span>', html)
        self.assertIn('<span class="kw">do</span>', html)
        self.assertIn('<span class="cm">-- load</span>', html)
        self.assertIn("saxpy", html)
        self.assertNotIn("<span class=\"kw\">saxpy</span>", html)

    def test_escapes_html(self) -> None:
        html = highlight_lean("if i.toUSize < xs.size then")
        self.assertIn("&lt;", html)
        self.assertNotIn("< xs", html)

    def test_block_wraps_pre(self) -> None:
        html = highlight_block("def f := 1")
        self.assertTrue(html.startswith('<pre class="lean"><code>'))
        self.assertTrue(html.endswith("</code></pre>"))


if __name__ == "__main__":
    unittest.main()
