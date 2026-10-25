"""Every public homepage text/accessible label must have a complete translation."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRANDS = {'Vertex Seven', 'V7 Agents', 'Starter', 'Business', 'Scale', 'WhatsApp',
          'info@vertex-seven.com', 'vertex-seven.com', 'V7 Agents by Vertex Seven'}


def translation_key(value):
    numbers = []

    def replace(match):
        numbers.append(match[0])
        return '{' + str(len(numbers)-1) + '}'

    return re.sub(r'(?<![\w])\d+(?:[.,]\d+)*(?![\w])', replace, value)


class PublicText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.values = [], set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        excluded = tag in {'script','style','option','code','pre'} or attrs.get('aria-hidden') == 'true' or 'data-no-i18n' in attrs
        if tag not in {'meta','link','img','br','input','hr'}:
            self.stack.append((tag, excluded))
        if not excluded:
            for name in ('aria-label', 'title', 'placeholder', 'alt'):
                if attrs.get(name):
                    self.values.add(attrs[name])
            if tag == 'meta' and (attrs.get('name') in {'description','twitter:title','twitter:description'}
                                  or attrs.get('property') in {'og:title','og:description'}):
                self.values.add(attrs['content'])

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(excluded for _, excluded in self.stack):
            value = re.sub(r'\s+', ' ', data).strip()
            if value and re.search('[A-Za-z]', value):
                self.values.add(value)


@pytest.mark.parametrize('vat', ['true', 'false'])
def test_homepage_translates_all_text_labels_and_pricing(client, monkeypatch, vat):
    monkeypatch.setenv('V7_VAT_REGISTERED', vat)
    response = client.get('/')
    assert response.status_code == 200
    parser = PublicText()
    parser.feed(response.text)
    for language in ('es', 'fr', 'ar'):
        entries = {}
        for name in ('ui', 'features', 'referrals', 'home'):
            entries.update(json.loads((ROOT/f'dashboard/static/i18n/{name}.json').read_text(encoding='utf-8'))[language])
        missing = [value for value in sorted(parser.values) if value not in BRANDS
                   and not entries.get(value) and not entries.get(translation_key(value))]
        assert not missing, (language, missing)


def test_home_translations_preserve_placeholders_and_are_complete():
    dictionary = json.loads((ROOT/'dashboard/static/i18n/home.json').read_text(encoding='utf-8'))
    assert set(dictionary) == {'es', 'fr', 'ar'}
    assert set(dictionary['es']) == set(dictionary['fr']) == set(dictionary['ar'])
    for language, entries in dictionary.items():
        for source, translated in entries.items():
            assert translated, (language, source)
            assert sorted(re.findall(r'\{\d+\}', source)) == sorted(re.findall(r'\{\d+\}', translated)), (language, source)
