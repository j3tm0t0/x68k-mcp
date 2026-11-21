import unittest
from types import SimpleNamespace
from unittest.mock import patch
from aws.calculator import calculate,handler


class ArithmeticTests(unittest.TestCase):
    def test_intermediate_steps_are_exact_and_decimal_literals_are_not_binary_floats(self):
        r=calculate('1024*(256-0xF0)/4000')
        self.assertEqual(r['decimal'],'4.096')
        self.assertIn({'expression':'1024*(256-0xF0)','exact':'16384'},r['steps'])
        self.assertEqual(calculate('0.425*8000')['exact'],'3400')
        self.assertEqual(calculate('38+2*16+4')['exact'],'74')
        self.assertTrue(calculate('1/3')['decimal_is_rounded'])

    def test_batch_frequency_calculations_preserve_exact_values_and_rounding(self):
        result=calculate('[4096000/1024,4096000/768,8000000/512]')
        self.assertEqual([r['exact'] for r in result['results']],['4000','16000/3','15625'])
        self.assertTrue(result['results'][1]['decimal_is_rounded'])
        for expression in ['[]','[True]','[[1]]','['+','.join(['1']*13)+']']:
            with self.subTest(expression=expression),self.assertRaises(ValueError):calculate(expression)

    def test_forbidden_code_excessive_arithmetic_and_zero_division(self):
        for expression in ['__import__("os")','(1).__class__','[1]*9','True','10**999','9**(9**9)','1/0','1e999','1+ '*100]:
            with self.subTest(expression=expression),self.assertRaises((ValueError,SyntaxError,ZeroDivisionError,OverflowError)):
                calculate(expression)
        good=SimpleNamespace(client_context=SimpleNamespace(custom={'bedrockAgentCoreToolName':'verification___calculate'}))
        self.assertEqual(handler({'expression':'2+2'},good)['exact'],'4')
        self.assertIn('error',handler({'expression':'2+2'},SimpleNamespace()))
        self.assertIn('error',handler({'expression':'2+2','extra':1},good))

    def test_scientific_exponent_is_rejected_before_fraction_expansion(self):
        with patch('aws.calculator.Fraction', side_effect=AssertionError('must reject before allocation')):
            for expression in ['1e999999999999', '1e-999999999999', '0e999999999999', '[1e999999999999]']:
                with self.subTest(expression=expression), self.assertRaises(ValueError):
                    calculate(expression)
        self.assertEqual(calculate('1e3/2')['exact'], '500')
        self.assertEqual(calculate('1.25e-2')['exact'], '1/80')
