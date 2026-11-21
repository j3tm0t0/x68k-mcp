"""Bounded exact rational arithmetic for verification; never evaluates Python code."""
import ast
from decimal import Decimal, localcontext
from fractions import Fraction


def calculate(expression):
    if not isinstance(expression,str) or not 1<=len(expression)<=256:
        raise ValueError('expression must contain 1..256 characters')
    tree=ast.parse(expression,mode='eval')
    if len(list(ast.walk(tree)))>64:raise ValueError('expression too complex')
    if isinstance(tree.body,ast.List):
        if not 1<=len(tree.body.elts)<=12 or any(isinstance(node,ast.List) for node in tree.body.elts):raise ValueError('calculate 1..12 scalar expressions per batch')
        return {'expression':expression,'results':[calculate(ast.get_source_segment(expression,node)) for node in tree.body.elts],
                'scope':'Independent exact arithmetic results. Verify formulas, units and source applicability separately.'}
    steps=[]
    def bounded(value):
        if value.numerator.bit_length()>512 or value.denominator.bit_length()>512:
            raise ValueError('arithmetic magnitude limit exceeded')
        return value
    def walk(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            literal=ast.get_source_segment(expression,node)
            # Fraction expands scientific exponents into integers; bound them first.
            if type(node.value) is float and 'e' in literal.lower():
                exponent=int(literal.lower().split('e',1)[1].replace('_',''))
                if abs(exponent)>150:
                    raise ValueError('decimal exponent limit exceeded')
            value=Fraction(node.value) if type(node.value) is int else Fraction(literal)
            return bounded(value)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=walk(node.operand);return -value if isinstance(node.op,ast.USub) else value
        if not isinstance(node,ast.BinOp):raise ValueError('only numeric literals and + - * / ** are allowed')
        a,b=walk(node.left),walk(node.right)
        if isinstance(node.op,ast.Add):value=a+b
        elif isinstance(node.op,ast.Sub):value=a-b
        elif isinstance(node.op,ast.Mult):value=a*b
        elif isinstance(node.op,ast.Div):value=a/b
        elif isinstance(node.op,ast.Pow) and b.denominator==1 and abs(b.numerator)<=16:value=a**b.numerator
        else:raise ValueError('unsupported operator or exponent')
        value=bounded(value)
        steps.append({'expression':ast.get_source_segment(expression,node),'exact':str(value)})
        return value
    value=walk(tree.body)
    with localcontext() as context:
        context.prec=28
        decimal=str(Decimal(value.numerator)/Decimal(value.denominator))
    return {'expression':expression,'exact':str(value),'decimal':decimal,
            'decimal_is_rounded':Fraction(decimal)!=value,'steps':steps,
            'scope':'Arithmetic only. Formula, units, assumptions and source applicability must be checked separately.'}


def handler(event,context):
    custom=getattr(getattr(context,'client_context',None),'custom',None) or {}
    if custom.get('bedrockAgentCoreToolName')!='verification___calculate':
        return {'error':'Unknown tool'}
    if not isinstance(event,dict) or set(event)!={'expression'}:
        return {'error':'Pass only expression'}
    try:return calculate(event['expression'])
    except (ValueError,SyntaxError,ZeroDivisionError,OverflowError):
        return {'error':'Invalid or out-of-bounds arithmetic expression'}
