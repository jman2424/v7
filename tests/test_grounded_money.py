from decimal import Decimal

import pytest

from service.grounded_money import extract_money_claims, monetary_claims_supported


@pytest.mark.parametrize('text', [
    'Basic costs £99.', 'Basic costs £99.00.', 'Basic costs GBP 99.00.',
    'Basic costs 99 GBP.', 'Basic costs 99.00 GBP.', 'Basic costs 99GBP.',
    'Basic costs 99 £.', 'Basic costs 99,00 GBP.', 'Basic costs gbp99.',
    'Le prix est de 99,00 £.', 'El precio es 99,00 GBP.',
    'السعر ٩٩٫٠٠ GBP.', 'السعر GBP ۹۹.۰۰.',
])
def test_supported_prefix_suffix_and_localized_prices(text):
    assert monetary_claims_supported(text, [{'price': 99, 'currency': 'GBP'}])


@pytest.mark.parametrize('text', [
    'Basic costs 999 GBP.', 'Basic costs 999USD.', 'Basic costs GBP 999.',
    'Basic costs 999 £.', 'السعر ٩٩٩ GBP.', 'El precio es 999,00 GBP.',
    'Le prix est de 999,00 £.', 'Basic costs -99 GBP.', 'Basic costs −99 £.',
    'Basic costs 99 EUR.', 'Basic costs $99.', 'Basic costs 99 €.',
    'Basic costs gbp999.',
])
def test_unsupported_suffix_values_and_different_currencies_rejected(text):
    assert not monetary_claims_supported(text, [{'price': 99, 'currency': 'GBP'}])


@pytest.mark.parametrize('text', [
    '€99,00', '99,00 EUR', 'EUR 99.00', '99 €',
])
def test_euro_decimal_comma_is_ninety_nine_not_nine_thousand(text):
    assert extract_money_claims(text) == {('EUR', Decimal('99'))}
    assert monetary_claims_supported(text, {'price': 99, 'currency': 'EUR'})
    assert not monetary_claims_supported(text, {'price': 9900, 'currency': 'EUR'})


@pytest.mark.parametrize('number', [
    '1,299.00', '1.299,00', '1 299,00', '1\u00a0299,00', '1\u202f299.00',
    '١٬٢٩٩٫٠٠', '۱٬۲۹۹٫۰۰',
])
@pytest.mark.parametrize('form', ['£{}', '{} GBP'])
def test_supported_grouped_decimal_numbers(number, form):
    text = form.format(number)
    assert extract_money_claims(text) == {('GBP', Decimal('1299'))}
    assert monetary_claims_supported(text, {'price': 1299, 'currency': 'GBP'})
    assert not monetary_claims_supported(text, {'price': '1.299', 'currency': 'GBP'})


@pytest.mark.parametrize('text', [
    '£1,29,9', '1.29.900 GBP', '£1,299,00',
    '£1 29,00', '1 299 00 EUR', '£01,299.00', '£1.00.00', '£99..00',
    '£9e2', '1e3 GBP', '£99abc', 'abc99 GBP', 'USD NaN', 'USD -Infinity', '99GBP99',
    '999. GBP', '999- GBP', '£.99',
])
def test_malformed_or_ambiguous_money_cannot_be_validated(text):
    assert extract_money_claims(text) is None
    assert not monetary_claims_supported(text, {'price': 99, 'currency': 'GBP'})


def test_many_grouping_separators_and_zero_integer_fractions_are_unambiguous():
    assert extract_money_claims('GBP 1,299,000; EUR 1.299.000; USD 0.001') == {
        ('GBP', Decimal('1299000')), ('EUR', Decimal('1299000')), ('USD', Decimal('0.001')),
    }


@pytest.mark.parametrize('text,currency', [
    ('£1,299', 'GBP'), ('$1,299', 'USD'), ('1.299 EUR', 'EUR'),
])
def test_single_thousands_separator_uses_conventional_currency_format(text, currency):
    assert extract_money_claims(text) == {(currency, Decimal('1299'))}
    assert monetary_claims_supported(text, {'price': 1299, 'currency': currency})
    assert not monetary_claims_supported(text, {'price': Decimal('1.299'), 'currency': currency})


@pytest.mark.parametrize('text,currency', [
    ('£0.085', 'GBP'), ('0,085 EUR', 'EUR'), ('$0.085', 'USD'), ('٩٩٫٩٩٩ GBP', 'GBP'),
])
def test_fractional_unit_prices_keep_precision(text, currency):
    amount = Decimal('99.999') if text.startswith('٩') else Decimal('0.085')
    assert monetary_claims_supported(text, {'price': amount, 'currency': currency})


def test_only_cited_money_or_structured_prices_establish_permission():
    claims = '£99 or €1299.00'
    facts = [{'price': '99.00', 'currency': 'GBP'},
             {'answer': 'La prestation coûte 1 299,00 EUR.'}]
    assert monetary_claims_supported(claims, facts)
    assert not monetary_claims_supported(claims, facts[:1])
    assert not monetary_claims_supported('£99', {'id': 99, 'stock': 99, 'days': '99'})
    assert not monetary_claims_supported('£99', {'£99 is a private key name': 'unknown'})
    assert not monetary_claims_supported('£99', [{'price': 99, 'currency': 'USD'}])


def test_structured_prices_preserve_decimal_precision_and_historical_default():
    assert monetary_claims_supported('£99.10', {'price': 99.1})
    assert monetary_claims_supported('$0.0001', {'price': Decimal('0.0001'), 'currency': 'usd'})
    assert not monetary_claims_supported('£99.11', {'price': Decimal('99.10'), 'currency': 'GBP'})


@pytest.mark.parametrize('value', [True, False, None, float('nan'), float('inf'), 'NaN', 'Infinity'])
def test_invalid_structured_price_does_not_supply_an_amount(value):
    assert not monetary_claims_supported('£1', {'price': value, 'currency': 'GBP'})


def test_numbers_without_currency_and_currency_descriptions_are_not_price_claims():
    assert monetary_claims_supported('Choose option 1. Prices are in GBP.', {})
    assert monetary_claims_supported('We can discuss your budget.', {})
    assert extract_money_claims('£99, and the second choice costs 199 GBP.') == {
        ('GBP', Decimal('99')), ('GBP', Decimal('199')),
    }


def test_malformed_evidence_does_not_authorize_a_claim():
    assert not monetary_claims_supported('£99', {'answer': '£99..00'})
    assert not monetary_claims_supported('£99', {'price': '99,00', 'currency': 'GBP'})
    assert not monetary_claims_supported('£99', {'price': 99, 'currency': 'NOTGBP'})


@pytest.mark.parametrize('question,answer', [
    ('I need a quiet office fan under 100 pounds.', 'Quiet costs £59, within your £100 budget.'),
    ('My budget is GBP 100.', 'This is within your budget of £100.'),
    ('My budget: £100.', 'Your budget is £100.'),
    ('Mi presupuesto es 100 euros.', 'Está dentro de tu presupuesto de 100 €.'),
    ('Mon budget est de 100 euros.', 'Cela respecte votre budget de 100 EUR.'),
    ('ميزانيتي ١٠٠ يورو', 'هذا ضمن ميزانيتك البالغة ١٠٠ EUR.'),
])
def test_explicit_customer_budget_can_be_repeated_as_a_budget(question, answer):
    assert monetary_claims_supported(answer, {'price': 59, 'currency': 'GBP'}, customer_text=[question])


@pytest.mark.parametrize('answer', [
    'The fan costs £100.',
    'Quiet costs £100, within your £100 budget.',
    'Your £100 budget option costs £100.',
    'The plan costs your £100 budget.',
    'Your £100 budget is our price.',
    'Your budget. This costs £100.',
    'Your budget option costs £100.',
    'Your budget is £100. The checkout total is £100.',
    'Your budget is £100abc.',
    'Your budget is £100..00.',
    'Your budget is £100e3.',
])
def test_budget_never_authorizes_business_prices_or_unlabelled_claims(answer):
    assert not monetary_claims_supported(answer, {'price': 59, 'currency': 'GBP'},
        customer_text=['I need a fan under 100 pounds.'])


@pytest.mark.parametrize('question,answer', [
    ('I need a fan under 100 euros.', 'Within your £100 budget.'),
    ('I need a fan under 100 pounds.', 'Within your $100 budget.'),
    ('I need a fan under 100.', 'Within your £100 budget.'),
    ('My budget is £100.', 'Within your £101 budget.'),
    ('My budget is £50. The old plan costs £100.', 'Within your £100 budget.'),
    ('Does the product cost 100 pounds?', 'Within your £100 budget.'),
    ('I weigh 100 pounds.', 'Within your £100 budget.'),
])
def test_budget_requires_exact_currency_amount_and_customer_budget_phrase(question, answer):
    assert not monetary_claims_supported(answer, {'price': 59, 'currency': 'GBP'}, customer_text=[question])


def test_budget_source_requires_explicit_customer_quote_list():
    answer = 'This fits your £100 budget.'
    assert not monetary_claims_supported(answer, {})
    assert not monetary_claims_supported(answer, {}, customer_text={'assistant': 'Your budget is £100.'})
    assert not monetary_claims_supported(answer, {}, customer_text='My budget is £100.')
    assert monetary_claims_supported(answer, {}, customer_text=['My budget is £100.'])


@pytest.mark.parametrize('phrase', [
    'your new budget of under £30', 'your updated budget of up to £30',
    'your current budget is now under £30', 'your revised budget below £30',
])
def test_revised_budget_can_be_repeated_alongside_real_prices(phrase):
    facts = [{'price': 59, 'currency': 'GBP'}, {'price': 129, 'currency': 'GBP'}]
    quotes = ['I need a quiet office fan under 100 pounds.',
              'Actually forget Quiet. My budget is now under 30 pounds, not under 100 pounds.']
    answer = f'I will use {phrase}. Neither listed fan fits: Quiet is £59 and Power is £129.'
    assert monetary_claims_supported(answer, facts, customer_text=quotes)
    # Neither the old nor new customer amount can establish a catalogue price.
    assert not monetary_claims_supported(answer + ' The new fan costs £30.', facts, customer_text=quotes)
    assert not monetary_claims_supported(answer + ' The new fan costs £100.', facts, customer_text=quotes)


def test_revised_budget_phrase_does_not_bridge_sentences_or_authorize_a_price():
    quotes = ['My budget is under 30 pounds.']
    assert not monetary_claims_supported('Your new budget. The fan costs £30.', {}, customer_text=quotes)
    assert not monetary_claims_supported('The fan costs your new budget of under £30.', {}, customer_text=quotes)
    assert not monetary_claims_supported('Your new budget of under £40.', {}, customer_text=quotes)
