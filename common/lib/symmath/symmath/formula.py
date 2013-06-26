#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# File:   formula.py
# Date:   04-May-12 (creation)
# Author: I. Chuang <ichuang@mit.edu>
#
# flexible python representation of a symbolic mathematical formula.
# Acceptes Presentation MathML, Content MathML (and could also do OpenMath)
# Provides sympy representation.

import os
import string       # pylint: disable=W0402
import re
import logging
import operator
import sympy
from sympy.printing.latex import LatexPrinter
from sympy.printing.str import StrPrinter
from sympy import latex, sympify
from sympy.physics.quantum.qubit import *
from sympy.physics.quantum.state import *
# from sympy import exp, pi, I
# from sympy.core.operations import LatticeOp
# import sympy.physics.quantum.qubit

from xml.sax.saxutils import unescape
import sympy
import unicodedata
from lxml import etree
#import subprocess
import requests
from copy import deepcopy

log = logging.getLogger(__name__)

log.warning("Dark code. Needs review before enabling in prod.")

os.environ['PYTHONIOENCODING'] = 'utf-8'

#-----------------------------------------------------------------------------


class dot(sympy.operations.LatticeOp):	 # my dot product
    zero = sympy.Symbol('dotzero')
    identity = sympy.Symbol('dotidentity')

#class dot(sympy.Mul):	# my dot product
#    is_Mul = False


def _print_dot(self, expr):
    return r'{((%s) \cdot (%s))}' % (expr.args[0], expr.args[1])

LatexPrinter._print_dot = _print_dot

#-----------------------------------------------------------------------------
# unit vectors (for 8.02)


def _print_hat(self, expr): return '\\hat{%s}' % str(expr.args[0]).lower()

LatexPrinter._print_hat = _print_hat
StrPrinter._print_hat = _print_hat

#-----------------------------------------------------------------------------
# helper routines


def to_latex(x):
    if x is None: return ''
    # LatexPrinter._print_dot = _print_dot
    xs = latex(x)
    xs = xs.replace(r'\XI', 'XI')	 # workaround for strange greek

    # substitute back into latex form for scripts
    # literally something of the form
    # 'scriptN' becomes '\\mathcal{N}'
    # note: can't use something akin to the _print_hat method above because we sometimes get 'script(N)__B' or more complicated terms
    xs = re.sub(r'script([a-zA-Z0-9]+)',
                '\\mathcal{\\1}',
                xs)

    #return '<math>%s{}{}</math>' % (xs[1:-1])
    if xs[0] == '$':
        return '[mathjax]%s[/mathjax]<br>' % (xs[1:-1])	 # for sympy v6
    return '[mathjax]%s[/mathjax]<br>' % (xs)		# for sympy v7


def my_evalf(expr, chop=False):
    if type(expr) == list:
        try:
            return [x.evalf(chop=chop) for x in expr]
        except:
            return expr
    try:
        return expr.evalf(chop=chop)
    except:
        return expr

#-----------------------------------------------------------------------------
# my version of sympify to import expression into sympy


def my_sympify(expr, normphase=False, matrix=False, abcsym=False, do_qubit=False, symtab=None):
    # make all lowercase real?
    if symtab:
        varset = symtab
    else:
        varset = {'p': sympy.Symbol('p'),
                  'g': sympy.Symbol('g'),
                  'e': sympy.E,			# for exp
                  'i': sympy.I,			# lowercase i is also sqrt(-1)
                  'Q': sympy.Symbol('Q'),	 # otherwise it is a sympy "ask key"
                  'I': sympy.Symbol('I'),	 # otherwise it is sqrt(-1)
                  'N': sympy.Symbol('N'),	 # or it is some kind of sympy function
                  #'X':sympy.sympify('Matrix([[0,1],[1,0]])'),
                  #'Y':sympy.sympify('Matrix([[0,-I],[I,0]])'),
                  #'Z':sympy.sympify('Matrix([[1,0],[0,-1]])'),
                  'ZZ': sympy.Symbol('ZZ'),	 # otherwise it is the PythonIntegerRing
                  'XI': sympy.Symbol('XI'),	 # otherwise it is the capital \XI
                  'hat': sympy.Function('hat'),	 # for unit vectors (8.02)
                  }
    if do_qubit:		# turn qubit(...) into Qubit instance
        varset.update({'qubit': sympy.physics.quantum.qubit.Qubit,
                       'Ket': sympy.physics.quantum.state.Ket,
                       'dot': dot,
                       'bit': sympy.Function('bit'),
                       })
    if abcsym:			# consider all lowercase letters as real symbols, in the parsing
        for letter in string.lowercase:
            if letter in varset:	 # exclude those already done
                continue
            varset.update({letter: sympy.Symbol(letter, real=True)})

    sexpr = sympify(expr, locals=varset)
    if normphase:	 # remove overall phase if sexpr is a list
        if type(sexpr) == list:
            if sexpr[0].is_number:
                ophase = sympy.sympify('exp(-I*arg(%s))' % sexpr[0])
                sexpr = [sympy.Mul(x, ophase) for x in sexpr]

    def to_matrix(x):		# if x is a list of lists, and is rectangular, then return Matrix(x)
        if not type(x) == list:
            return x
        for row in x:
            if (not type(row) == list):
                return x
        rdim = len(x[0])
        for row in x:
            if not len(row) == rdim:
                return x
        return sympy.Matrix(x)

    if matrix:
        sexpr = to_matrix(sexpr)
    return sexpr

#-----------------------------------------------------------------------------
# class for symbolic mathematical formulas


class formula(object):
    '''
    Representation of a mathematical formula object.  Accepts mathml math expression
    for constructing, and can produce sympy translation.  The formula may or may not
    include an assignment (=).
    '''
    def __init__(self, expr, asciimath='', options=None):
        self.expr = expr.strip()
        self.asciimath = asciimath
        self.the_cmathml = None
        self.the_sympy = None
        self.options = options

    def is_presentation_mathml(self):
        return '<mstyle' in self.expr

    def is_mathml(self):
        return '<math ' in self.expr

    def fix_greek_in_mathml(self, xml):
        def gettag(x):
            return re.sub('{http://[^}]+}', '', x.tag)

        for k in xml:
            tag = gettag(k)
            if tag == 'mi' or tag == 'ci':
                usym = unicode(k.text)
                try:
                    udata = unicodedata.name(usym)
                except Exception, err:
                    udata = None
                #print "usym = %s, udata=%s" % (usym,udata)
                if udata:			# eg "GREEK SMALL LETTER BETA"
                    if 'GREEK' in udata:
                        usym = udata.split(' ')[-1]
                        if 'SMALL' in udata: usym = usym.lower()
                        #print "greek: ",usym
                k.text = usym
            self.fix_greek_in_mathml(k)
        return xml

    def preprocess_pmathml(self, xml):
        r'''
        Pre-process presentation MathML from ASCIIMathML to make it more
        acceptable for SnuggleTeX, and also to accomodate some sympy
        conventions (eg hat(i) for \hat{i}).

        This method would be a good spot to look for an integral and convert
        it, if possible...
        '''

        if type(xml) == str or type(xml) == unicode:
            xml = etree.fromstring(xml)		# TODO: wrap in try

        xml = self.fix_greek_in_mathml(xml)	 # convert greek utf letters to greek spelled out in ascii

        def gettag(x):
            return re.sub('{http://[^}]+}', '', x.tag)

        # f and g are processed as functions by asciimathml, eg  "f-2" turns into "<mrow><mi>f</mi><mo>-</mo></mrow><mn>2</mn>"
        # this is really terrible for turning into cmathml.
        # undo this here.
        def fix_pmathml(xml):
            for k in xml:
                tag = gettag(k)
                if tag == 'mrow':
                    if len(k) == 2:
                        if gettag(k[0]) == 'mi' and k[0].text in ['f', 'g'] and gettag(k[1]) == 'mo':
                            idx = xml.index(k)
                            xml.insert(idx, deepcopy(k[0]))	 # drop the <mrow> container
                            xml.insert(idx + 1, deepcopy(k[1]))
                            xml.remove(k)
                fix_pmathml(k)

        fix_pmathml(xml)

        # hat i is turned into <mover><mi>i</mi><mo>^</mo></mover> ; mangle this into <mi>hat(f)</mi>
        # hat i also somtimes turned into <mover><mrow> <mi>j</mi> </mrow><mo>^</mo></mover>

        def fix_hat(xml):
            for k in xml:
                tag = gettag(k)
                if tag == 'mover':
                    if len(k) == 2:
                        if gettag(k[0]) == 'mi' and gettag(k[1]) == 'mo' and str(k[1].text) == '^':
                            newk = etree.Element('mi')
                            newk.text = 'hat(%s)' % k[0].text
                            xml.replace(k, newk)
                        if gettag(k[0]) == 'mrow' and gettag(k[0][0]) == 'mi' and gettag(k[1]) == 'mo' and str(k[1].text) == '^':
                            newk = etree.Element('mi')
                            newk.text = 'hat(%s)' % k[0][0].text
                            xml.replace(k, newk)
                fix_hat(k)
        fix_hat(xml)

        def flatten_pmathml(xml):
            ''' Give the text version of certain PMathML elements

            Sometimes MathML will be given with each letter separated (it
            doesn't know if its implicit multiplication or what). From an xml
            node, find the (text only) variable name it represents. So it takes
            <mrow>
              <mi>m</mi>
              <mi>a</mi>
              <mi>x</mi>
            </mrow>
            and returns 'max', for easier use later on.
            '''
            tag = gettag(xml)
            if tag == 'mn': return xml.text
            elif tag == 'mi': return xml.text
            elif tag == 'mrow': return ''.join([flatten_pmathml(y) for y in xml])
            raise Exception, '[flatten_pmathml] unknown tag %s' % tag

        def fix_mathvariant(parent):
            '''Fix certain kinds of math variants

            Literally replace <mstyle mathvariant="script"><mi>N</mi></mstyle>
            with 'scriptN'. There have been problems using script_N or script(N)
            '''
            for child in parent:
                if (gettag(child) == 'mstyle' and child.get('mathvariant') == 'script'):
                    newchild = etree.Element('mi')
                    newchild.text = 'script%s' % flatten_pmathml(child[0])
                    parent.replace(child, newchild)
                fix_mathvariant(child)
        fix_mathvariant(xml)


        # find "tagged" superscripts
        # they have the character \u200b in the superscript
        # replace them with a__b so snuggle doesn't get confused
        def fix_superscripts(xml):
            ''' Look for and replace sup elements with 'X__Y' or 'X_Y__Z'

            In the javascript, variables with '__X' in them had an invisible
            character inserted into the sup (to distinguish from powers)
            E.g. normal:
            <msubsup>
              <mi>a</mi>
              <mi>b</mi>
              <mi>c</mi>
            </msubsup>
            to be interpreted '(a_b)^c' (nothing done by this method)

            And modified:
            <msubsup>
              <mi>b</mi>
              <mi>x</mi>
              <mrow>
                <mo>&#x200B;</mo>
                <mi>d</mi>
              </mrow>
            </msubsup>
            to be interpreted 'a_b__c'

            also:
            <msup>
              <mi>x</mi>
              <mrow>
                <mo>&#x200B;</mo>
                <mi>B</mi>
              </mrow>
            </msup>
            to be 'x__B'
            '''
            for k in xml:
                tag = gettag(k)

                # match things like the last example--
                # the second item in msub is an mrow with the first
                # character equal to \u200b
                if (tag == 'msup' and
                    len(k) == 2 and gettag(k[1]) == 'mrow' and
                    gettag(k[1][0]) == 'mo' and k[1][0].text == u'\u200b'): # whew

                    # replace the msup with 'X__Y'
                    k[1].remove(k[1][0])
                    newk = etree.Element('mi')
                    newk.text = '%s__%s' % (flatten_pmathml(k[0]), flatten_pmathml(k[1]))
                    xml.replace(k, newk)

                # match things like the middle example-
                # the third item in msubsup is an mrow with the first
                # character equal to \u200b
                if (tag == 'msubsup' and
                    len(k) == 3 and gettag(k[2]) == 'mrow' and
                    gettag(k[2][0]) == 'mo' and k[2][0].text == u'\u200b'): # whew

                    # replace the msubsup with 'X_Y__Z'
                    k[2].remove(k[2][0])
                    newk = etree.Element('mi')
                    newk.text = '%s_%s__%s' % (flatten_pmathml(k[0]), flatten_pmathml(k[1]), flatten_pmathml(k[2]))
                    xml.replace(k, newk)

                fix_superscripts(k)
        fix_superscripts(xml)

        # Snuggle returns an error when it sees an <msubsup>
        # replace such elements with an <msup>, except the first element is of
        # the form a_b. I.e. map a_b^c => (a_b)^c
        def fix_msubsup(parent):
            for child in parent:
                # fix msubsup
                if (gettag(child) == 'msubsup' and len(child) == 3):
                    newchild = etree.Element('msup')
                    newbase = etree.Element('mi')
                    newbase.text = '%s_%s' % (flatten_pmathml(child[0]), flatten_pmathml(child[1]))
                    newexp = child[2]
                    newchild.append(newbase)
                    newchild.append(newexp)
                    parent.replace(child, newchild)

                fix_msubsup(child)
        fix_msubsup(xml)

        self.xml = xml
        return self.xml

    def get_content_mathml(self):
        if self.the_cmathml: return self.the_cmathml

        # pre-process the presentation mathml before sending it to snuggletex to convert to content mathml
        try:
            xml = self.preprocess_pmathml(self.expr)
        except Exception, err:
            log.warning('Err %s while preprocessing; expr=%s' % (err, self.expr))
            return "<html>Error! Cannot process pmathml</html>"
        pmathml = etree.tostring(xml, pretty_print=True)
        self.the_pmathml = pmathml

        # convert to cmathml
        self.the_cmathml = self.GetContentMathML(self.asciimath, pmathml)
        return self.the_cmathml

    cmathml = property(get_content_mathml, None, None, 'content MathML representation')

    def make_sympy(self, xml=None):
        '''
        Return sympy expression for the math formula.
        The math formula is converted to Content MathML then that is parsed.

        This is a recursive function, called on every CMML node. Support for
        more functions can be added by modifying opdict, abould halfway down
        '''

        if self.the_sympy: return self.the_sympy

        if xml is None:	 # root
            if not self.is_mathml():
                return my_sympify(self.expr)
            if self.is_presentation_mathml():
                cmml = None
                try:
                    cmml = self.cmathml
                    xml = etree.fromstring(str(cmml))
                except Exception, err:
                    if 'conversion from Presentation MathML to Content MathML was not successful' in cmml:
                        msg = "Illegal math expression"
                    else:
                        msg = 'Err %s while converting cmathml to xml; cmml=%s' % (err, cmml)
                    raise Exception, msg
                xml = self.fix_greek_in_mathml(xml)
                self.the_sympy = self.make_sympy(xml[0])
            else:
                xml = etree.fromstring(self.expr)
                xml = self.fix_greek_in_mathml(xml)
                self.the_sympy = self.make_sympy(xml[0])
            return self.the_sympy

        def gettag(x):
            return re.sub('{http://[^}]+}', '', x.tag)

        # simple math
        def op_divide(*args):
            if not len(args) == 2:
                raise Exception, 'divide given wrong number of arguments!'
            # print "divide: arg0=%s, arg1=%s" % (args[0],args[1])
            return sympy.Mul(args[0], sympy.Pow(args[1], -1))

        def op_plus(*args): return args[0] if len(args) == 1 else op_plus(*args[:-1]) + args[-1]

        def op_times(*args): return reduce(operator.mul, args)

        def op_minus(*args):
            if len(args) == 1:
                return -args[0]
            if not len(args) == 2:
                raise Exception, 'minus given wrong number of arguments!'
            #return sympy.Add(args[0],-args[1])
            return args[0] - args[1]

        opdict = {'plus': op_plus,
                  'divide': operator.div,
                  'times': op_times,
                  'minus': op_minus,
                  #'plus': sympy.Add,
                  #'divide' : op_divide,
                  #'times' : sympy.Mul,
                  'minus': op_minus,
                  'root': sympy.sqrt,
                  'power': sympy.Pow,
                  'sin': sympy.sin,
                  'cos': sympy.cos,
                  'tan': sympy.tan,
                  'cot': sympy.cot,
                  'sinh': sympy.sinh,
                  'cosh': sympy.cosh,
                  'coth': sympy.coth,
                  'tanh': sympy.tanh,
                  'asin': sympy.asin,
                  'acos': sympy.acos,
                  'atan': sympy.atan,
                  'atan2': sympy.atan2,
                  'acot': sympy.acot,
                  'asinh': sympy.asinh,
                  'acosh': sympy.acosh,
                  'atanh': sympy.atanh,
                  'acoth': sympy.acoth,
                  'exp': sympy.exp,
                  'log': sympy.log,
                  'ln': sympy.ln,
                   }

        # simple sumbols
        nums1dict = {'pi': sympy.pi,
                     }

        def parsePresentationMathMLSymbol(xml):
            '''
            Parse <msub>, <msup>, <mi>, and <mn>
            '''
            tag = gettag(xml)
            if tag == 'mn': return xml.text
            elif tag == 'mi': return xml.text
            elif tag == 'msub': return '_'.join([parsePresentationMathMLSymbol(y) for y in xml])
            elif tag == 'msup': return '^'.join([parsePresentationMathMLSymbol(y) for y in xml])
            raise Exception, '[parsePresentationMathMLSymbol] unknown tag %s' % tag

        # parser tree for Content MathML
        tag = gettag(xml)
        # print "tag = ",tag

        # first do compound objects

        if tag == 'apply':		# apply operator
            opstr = gettag(xml[0])
            if opstr in opdict:
                op = opdict[opstr]
                args = [self.make_sympy(x) for x in xml[1:]]
                try:
                    res = op(*args)
                except Exception, err:
                    self.args = args
                    self.op = op
                    raise Exception, '[formula] error=%s failed to apply %s to args=%s' % (err, opstr, args)
                return res
            else:
                raise Exception, '[formula]: unknown operator tag %s' % (opstr)

        elif tag == 'list':		# square bracket list
            if gettag(xml[0]) == 'matrix':
                return self.make_sympy(xml[0])
            else:
                return [self.make_sympy(x) for x in xml]

        elif tag == 'matrix':
            return sympy.Matrix([self.make_sympy(x) for x in xml])

        elif tag == 'vector':
            return [self.make_sympy(x) for x in xml]

        # atoms are below

        elif tag == 'cn':			# number
            return sympy.sympify(xml.text)
            return float(xml.text)

        elif tag == 'ci':			# variable (symbol)
            if len(xml) > 0 and (gettag(xml[0]) == 'msub' or gettag(xml[0]) == 'msup'):	 # subscript or superscript
                usym = parsePresentationMathMLSymbol(xml[0])
                sym = sympy.Symbol(str(usym))
            else:
                usym = unicode(xml.text)
                if 'hat' in usym:
                    sym = my_sympify(usym)
                else:
                    if usym == 'i' and self.options is not None and 'imaginary' in self.options:	 # i = sqrt(-1)
                        sym = sympy.I
                    else:
                        sym = sympy.Symbol(str(usym))
            return sym

        else:				# unknown tag
            raise Exception, '[formula] unknown tag %s' % tag

    sympy = property(make_sympy, None, None, 'sympy representation')

    def GetContentMathML(self, asciimath, mathml):
        # URL = 'http://192.168.1.2:8080/snuggletex-webapp-1.2.2/ASCIIMathMLUpConversionDemo'
        # URL = 'http://127.0.0.1:8080/snuggletex-webapp-1.2.2/ASCIIMathMLUpConversionDemo'
        URL = 'https://math-xserver.mitx.mit.edu/snuggletex-webapp-1.2.2/ASCIIMathMLUpConversionDemo'

        if 1:
            payload = {'asciiMathInput': asciimath,
                       'asciiMathML': mathml,
                       #'asciiMathML':unicode(mathml).encode('utf-8'),
                       }
            headers = {'User-Agent': "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) Gecko/20080311 Firefox/2.0.0.13"}
            r = requests.post(URL, data=payload, headers=headers, verify=False)
            r.encoding = 'utf-8'
            ret = r.text
            #print "encoding: ",r.encoding

        # return ret

        mode = 0
        cmathml = []
        for k in ret.split('\n'):
            if 'conversion to Content MathML' in k:
                mode = 1
                continue
            if mode == 1:
                if '<h3>Maxima Input Form</h3>' in k:
                    mode = 0
                    continue
                cmathml.append(k)
        # return '\n'.join(cmathml)
        cmathml = '\n'.join(cmathml[2:])
        cmathml = '<math xmlns="http://www.w3.org/1998/Math/MathML">\n' + unescape(cmathml) + '\n</math>'
        # print cmathml
        #return unicode(cmathml)
        return cmathml

#-----------------------------------------------------------------------------


def test1():
    xmlstr = '''
<math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply>
      <plus/>
      <cn>1</cn>
      <cn>2</cn>
   </apply>
</math>
    '''
    return formula(xmlstr)


def test2():
    xmlstr = u'''
<math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply>
      <plus/>
      <cn>1</cn>
      <apply>
         <times/>
         <cn>2</cn>
     <ci>α</ci>
      </apply>
   </apply>
</math>
    '''
    return formula(xmlstr)


def test3():
    xmlstr = '''
<math xmlns="http://www.w3.org/1998/Math/MathML">
   <apply>
      <divide/>
      <cn>1</cn>
      <apply>
         <plus/>
         <cn>2</cn>
         <ci>γ</ci>
      </apply>
   </apply>
</math>
    '''
    return formula(xmlstr)


def test4():
    xmlstr = u'''
<math xmlns="http://www.w3.org/1998/Math/MathML">
  <mstyle displaystyle="true">
    <mn>1</mn>
    <mo>+</mo>
    <mfrac>
      <mn>2</mn>
      <mi>α</mi>
    </mfrac>
  </mstyle>
</math>
'''
    return formula(xmlstr)


def test5():		# sum of two matrices
    xmlstr = u'''
<math xmlns="http://www.w3.org/1998/Math/MathML">
  <mstyle displaystyle="true">
    <mrow>
      <mi>cos</mi>
      <mrow>
        <mo>(</mo>
        <mi>&#x3B8;</mi>
        <mo>)</mo>
      </mrow>
    </mrow>
    <mo>&#x22C5;</mo>
    <mrow>
      <mo>[</mo>
      <mtable>
        <mtr>
          <mtd>
            <mn>1</mn>
          </mtd>
          <mtd>
            <mn>0</mn>
          </mtd>
        </mtr>
        <mtr>
          <mtd>
            <mn>0</mn>
          </mtd>
          <mtd>
            <mn>1</mn>
          </mtd>
        </mtr>
      </mtable>
      <mo>]</mo>
    </mrow>
    <mo>+</mo>
    <mrow>
      <mo>[</mo>
      <mtable>
        <mtr>
          <mtd>
            <mn>0</mn>
          </mtd>
          <mtd>
            <mn>1</mn>
          </mtd>
        </mtr>
        <mtr>
          <mtd>
            <mn>1</mn>
          </mtd>
          <mtd>
            <mn>0</mn>
          </mtd>
        </mtr>
      </mtable>
      <mo>]</mo>
    </mrow>
  </mstyle>
</math>
'''
    return formula(xmlstr)


def test6():		# imaginary numbers
    xmlstr = u'''
<math xmlns="http://www.w3.org/1998/Math/MathML">
  <mstyle displaystyle="true">
    <mn>1</mn>
    <mo>+</mo>
    <mi>i</mi>
  </mstyle>
</math>
'''
    return formula(xmlstr, options='imaginary')
