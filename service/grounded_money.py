"""Currency-aware validation of quoted amounts against cited public facts.

This checks existing amounts only: it never calculates prices, discounts, tax or
currency conversions. Grouping must be well formed; a lone three-digit group
uses GBP/USD comma or EUR dot conventions. Explicit Arabic decimal marks and
zero integer fractions retain their exact precision.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re
import unicodedata


Money = tuple[str, Decimal]
_CURRENCIES = {'£': 'GBP', '$': 'USD', '€': 'EUR',
               'GBP': 'GBP', 'USD': 'USD', 'EUR': 'EUR'}
_CURRENCY = r'(?:[£$€]|(?<![^\W\d])(?:GBP|USD|EUR)(?![^\W\d]))'
_SPACE = r'[ \t\u00a0\u202f]'
_NUMBER = rf'[+\-−]?\d+(?:(?:[.,٫٬]\d+)|(?:{_SPACE}+\d+))*'
_PREFIX = re.compile(rf'(?P<currency>{_CURRENCY})\s*(?P<number>{_NUMBER})', re.I)
_SUFFIX = re.compile(rf'(?<![\w.,٫٬])(?P<number>{_NUMBER})\s*(?P<currency>{_CURRENCY})', re.I)
_CURRENCY_TOKEN = re.compile(_CURRENCY, re.I)
_BUDGET_CURRENCY_WORDS = {
    'pound': 'GBP', 'pounds': 'GBP', 'pound sterling': 'GBP', 'pounds sterling': 'GBP',
    'libra': 'GBP', 'libras': 'GBP', 'libras esterlinas': 'GBP', 'livres sterling': 'GBP',
    'جنيه إسترليني': 'GBP', 'جنيهات إسترلينية': 'GBP',
    'euro': 'EUR', 'euros': 'EUR', 'يورو': 'EUR',
    'US dollar': 'USD', 'US dollars': 'USD', 'dólares estadounidenses': 'USD',
    'dollars américains': 'USD', 'دولار أمريكي': 'USD',
}
_BUDGET_WORDS = '|'.join(re.escape(word) for word in sorted(_BUDGET_CURRENCY_WORDS, key=len, reverse=True))
_BUDGET_CURRENCY = rf'(?:{_CURRENCY}|(?<!\w)(?:{_BUDGET_WORDS})(?!\w))'
_BUDGET_MONEY = (rf'(?:{_BUDGET_CURRENCY}\s*{_NUMBER}(?![\w٫٬]|[.,][\d.,٫٬])|'
                 rf'(?<![\w.,٫٬]){_NUMBER}\s*{_BUDGET_CURRENCY})')
_CUSTOMER_BUDGET = tuple(re.compile(pattern + rf'\s*[:=]?\s*(?P<money>{_BUDGET_MONEY})', re.I)
    for pattern in (
        r'\b(?:(?:my|our)\s+(?:budget|limit)(?:\s+(?:is|of|was|at))?|under|below|up to|'
        r'at most|less than|no more than|maximum(?: of)?|(?:can|want to|willing to) spend)',
        r'\b(?:(?:mi|nuestro)\s+(?:presupuesto|límite)(?:\s+(?:es|de))?|menos de|hasta|máximo de)',
        r"\b(?:(?:mon|notre)\s+budget(?:\s+(?:est|de|est de))?|moins de|jusqu['’]à|maximum de|au plus)",
        r'(?:ميزانيتي(?:\s+(?:هي|تبلغ|بحدود))?|أقل من|حتى|حد أقصى)',
    )) + (re.compile(rf'(?P<money>{_BUDGET_MONEY})\s+(?:budget|maximum|limit)\b', re.I),)
_ANSWER_BUDGET = tuple(re.compile(pattern, re.I) for pattern in (
    rf'\b(?:with|given)\s+(?:a|the|your)\s+(?:(?:new|current|updated|revised|stated)\s+)?'
    rf'budget(?:\s+of)?\s*:?\s*(?P<money>{_BUDGET_MONEY})',
    rf'\byour\s+(?P<money>{_BUDGET_MONEY})\s+budget\b',
    (rf'\byour\s+(?:(?:new|current|updated|revised|stated)\s+)?budget'
     rf'(?:\s+(?:of|is|was|at))?(?:\s+now(?:\s+at)?)?'
     rf'(?:\s+(?:under|below|up to|at most|less than|no more than))?'
     rf'\s*:?\s*(?P<money>{_BUDGET_MONEY})'),
    rf'\b(?:tu|su|vuestro)\s+presupuesto(?:\s+(?:de|es|es de))?\s*:?\s*(?P<money>{_BUDGET_MONEY})',
    rf'\bvotre\s+budget(?:\s+(?:de|est|est de))?\s*:?\s*(?P<money>{_BUDGET_MONEY})',
    rf'ميزانيتك(?:\s+(?:البالغة|هي|تبلغ|بحدود))?\s*:?\s*(?P<money>{_BUDGET_MONEY})',
))


def _ascii_number(value: str) -> str:
    return ''.join(str(unicodedata.decimal(char)) if char.isdecimal() else char
                   for char in value).replace('−', '-').replace('٫', '.').replace('٬', ',')


def _grouped_integer(value: str, separator: str) -> str | None:
    groups = value.split(separator)
    if (not 1 <= len(groups[0]) <= 3 or not groups[0].isdigit()
            or groups[0].startswith('0')
            or any(len(group) != 3 or not group.isdigit() for group in groups[1:])):
        return None
    return ''.join(groups)


def _amount(value: str, currency: str) -> Decimal | None:
    """Parse unambiguous grouped or decimal monetary notation exactly."""
    number = _ascii_number(value)
    sign = ''
    if number.startswith(('+', '-')):
        sign, number = number[0], number[1:]
    number = re.sub(_SPACE + '+', ' ', number)
    decimal = None
    if '.' in number and ',' in number:
        decimal = '.' if number.rfind('.') > number.rfind(',') else ','
        group = ',' if decimal == '.' else '.'
        if number.count(decimal) != 1 or ' ' in number:
            return None
        integer, fraction = number.split(decimal)
        integer = _grouped_integer(integer, group)
        if integer is None or not fraction.isdigit():
            return None
        normalized = integer + '.' + fraction
    elif ' ' in number:
        separators = [char for char in '.,' if char in number]
        if separators:
            decimal = separators[0]
            if number.count(decimal) != 1:
                return None
            integer, fraction = number.split(decimal)
            if not fraction.isdigit():
                return None
        else:
            integer, fraction = number, None
        integer = _grouped_integer(integer, ' ')
        if integer is None:
            return None
        normalized = integer + ('.' + fraction if fraction is not None else '')
    elif '.' in number or ',' in number:
        separator = '.' if '.' in number else ','
        if number.count(separator) > 1:
            normalized = _grouped_integer(number, separator)
            if normalized is None:
                return None
        else:
            integer, fraction = number.split(separator)
            if not fraction:
                return None
            # Resolve a lone three-digit grouping by the quoted currency's
            # conventional notation. Explicit Arabic decimal marks and a zero
            # integer always denote a fraction, preserving small unit prices.
            grouping = (len(fraction) == 3 and integer != '0' and '٫' not in value
                        and ((separator == ',' and currency in {'GBP', 'USD'})
                             or (separator == '.' and currency == 'EUR')))
            normalized = (_grouped_integer(number, separator) if grouping
                          else integer + '.' + fraction)
            if normalized is None:
                return None
    else:
        normalized = number
    try:
        parsed = Decimal(sign + normalized)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def extract_money_claims(text: str) -> set[Money] | None:
    """Return amounts in text, or None when a monetary amount is malformed.

    GBP/USD/EUR codes and their symbols are accepted on either side. Unicode
    decimal digits and Arabic decimal/grouping separators are supported. Lone
    currency references, such as "prices are in GBP", make no amount claim.
    """
    claims: set[Money] = set()
    covered = set()
    for pattern in (_PREFIX, _SUFFIX):
        for match in pattern.finditer(text):
            number = match.group('number')
            currency = _CURRENCIES[match.group('currency').upper()]
            amount = _amount(number, currency)
            start, end = match.span('number')
            # Do not accept a partial scientific notation or malformed amount.
            before, after = text[:start], text[end:]
            if (amount is None
                    or (before and before[-1] in '.,٫٬')
                    or (after and (after[0].isalnum() or after[0] in '٫٬'))
                    or (after[:1] in {'.', ','} and len(after) > 1 and after[1] in '.,٫٬')):
                # Adjacent suffix codes are ordinary monetary notation, not an
                # attached identifier (99GBP). They get their own currency check.
                if (amount is None or not re.match(r'^(?:GBP|USD|EUR)(?!\w)', after, re.I)
                        or (before and before[-1] in '.,٫٬')):
                    return None
            claims.add((currency, amount))
            covered.add(match.span('currency'))
    for match in _CURRENCY_TOKEN.finditer(text):
        left, right = text[:match.start()].rstrip(), text[match.end():].lstrip()
        if left and right and left[-1].isdecimal() and right[0].isdecimal():
            return None
        if match.span() in covered:
            continue
        # A malformed number must not disappear simply because a regex cannot
        # match it, for example "1e3 GBP" or "USD -NaN" is not price evidence.
        numeric_left = left.rstrip('.,٫٬+-−')
        numeric_right = right.lstrip('.,٫٬+-−')
        if ((numeric_left and numeric_left[-1].isdecimal())
                or (numeric_right and numeric_right[0].isdecimal())
                or re.match(r'^[+\-−]?(?:nan|inf(?:inity)?)(?!\w)', right, re.I)):
            return None
    return claims


def _structured_price(row: Mapping) -> Money | None:
    value = row.get('price')
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        return None
    currency = row.get('currency', 'GBP')
    if not isinstance(currency, str):
        return None
    currency = _CURRENCIES.get(currency.upper())
    if currency is None:
        return None
    try:
        # Numeric price fields are machine numbers; do not interpret separators
        # or currency conversions. Decimal(str(...)) avoids binary float rounding.
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    return (currency, price) if price.is_finite() else None


def _budget_amounts(text: str) -> set[Money] | None:
    # Currency words are interpreted only inside an explicit budget phrase;
    # "100 pounds" elsewhere may be a weight rather than a monetary amount.
    for word, currency in sorted(_BUDGET_CURRENCY_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(r'(?<!\w)' + re.escape(word) + r'(?!\w)', currency, text, flags=re.I)
    return extract_money_claims(text)


def unqualified_customer_budget(requirements: object) -> Money | None:
    """Use only one whole, current budget requirement for listed-price labels.

    These server-verified requirements describe the active customer request.
    Amount validation alone cannot establish quantity, recurring or other scope.
    Be conservative when a requirement contains any such qualification.
    """
    if not isinstance(requirements, list):
        return None
    budgets: set[Money] = set()
    for quote in requirements:
        if not isinstance(quote, str):
            return None
        text = quote.strip().rstrip('.!?').strip()
        match = next((match for pattern in _CUSTOMER_BUDGET
                      if (match := pattern.fullmatch(text))), None)
        if match:
            if (re.search(r'\bwas\b', text, re.I)
                    or re.match(r'(?:under|below|less than|menos de|moins de|أقل من)\b', text, re.I)):
                return None
            amounts = _budget_amounts(match['money'])
            if not amounts or len(amounts) != 1:
                return None
            budgets.update(amounts)
        elif re.search(r'\d|\b(?:budget|limit|presupuesto|ميزاني|one|two|three|four|five|six|seven|'
                       r'eight|nine|ten|dozen|pair|pairs|couple|multiple|several|each|per|monthly|weekly|daily|yearly|annually)\b',
                       text, re.I):
            return None
    return next(iter(budgets)) if len(budgets) == 1 else None


def _without_customer_budgets(text: str, customer_text: object) -> str | None:
    allowed: set[Money] = set()
    if isinstance(customer_text, (list, tuple)):
        for quote in customer_text:
            if isinstance(quote, str):
                for pattern in _CUSTOMER_BUDGET:
                    for match in pattern.finditer(quote):
                        allowed.update(_budget_amounts(match['money']) or set())
    spans = []
    for pattern in _ANSWER_BUDGET:
        for match in pattern.finditer(text):
            amounts = _budget_amounts(match['money'])
            before, after = text[:match.start()], text[match.end():]
            # "Within/above your budget at £20" quotes an offering price,
            # not a different customer budget. Leave it visible for the normal
            # cited price check instead of masking it as customer-supplied money.
            if (re.search(r'\b(?:within|under|below|fits?|meets?|above|over|outside|exceeds?)\s*$', before, re.I)
                    and re.match(r'(?i)your\s+(?:(?:new|current|updated|revised|stated)\s+)?'
                                 r'budget\s+at\s+', match.group())):
                continue
            if (not amounts or not amounts.issubset(allowed)
                    or re.search(r'\b(?:costs?|charges?|priced at|price of|pay)\s*$', before, re.I)
                    or re.match(r'\s+(?:is|will be)\s+(?:our |the )?(?:price|cost|charge)\b', after, re.I)):
                return None
            spans.append(match.span('money'))
    # Mask individual verified budget mentions, not every occurrence of the
    # amount: "costs £100, within your £100 budget" still needs a £100 price.
    for start, end in sorted(set(spans), reverse=True):
        text = text[:start] + ' ' * (end - start) + text[end:]
    return text


def monetary_claims_supported(text: str, cited_knowledge: object, *, customer_text: object = ()) -> bool:
    """Validate answer amounts against only the caller's cited public facts.

    Pass a list/dict of already authorized, cited knowledge values, never the
    entire tenant catalogue. Bare numbers (IDs, stock, dates, budgets) do not
    establish a price. Existing structured price fields default to GBP for
    compatibility with catalogues that omit their historical default currency.
    Optional customer_text contains only server-selected customer quotes. Their
    explicitly stated budgets can support narrowly labelled budget restatements,
    never offering prices, conversions or arbitrary repeated monetary claims.
    """
    text = _without_customer_budgets(text, customer_text)
    if text is None:
        return False
    claims = extract_money_claims(text)
    if claims is None:
        return False
    permitted: set[Money] = set()

    def collect(value: object) -> None:
        if isinstance(value, str):
            permitted.update(extract_money_claims(value) or set())
        elif isinstance(value, Mapping):
            price = _structured_price(value)
            if price is not None:
                permitted.add(price)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(cited_knowledge)
    return claims.issubset(permitted)
