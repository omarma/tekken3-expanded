"""Convert HTML to plain text, stripping tags."""
import html.parser
import re
import sys

class HTMLToText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav'):
            self.skip = True
        if tag in ('p', 'br', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'tr', 'pre'):
            self.text.append('\n')
        if tag == 'td':
            self.text.append('\t')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav'):
            self.skip = False
        if tag in ('h1', 'h2', 'h3', 'h4', 'pre'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)

def main():
    src = sys.argv[1]
    dst = sys.argv[2]
    with open(src, 'r', encoding='utf-8') as f:
        content = f.read()
    p = HTMLToText()
    p.feed(content)
    text = ''.join(p.text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'wrote {len(text)} chars')

if __name__ == '__main__':
    main()
