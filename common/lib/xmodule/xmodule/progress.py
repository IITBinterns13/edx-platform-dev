'''
Progress class for modules.  Represents where a student is in a module.

Useful things to know:
 - Use Progress.to_js_status_str() to convert a progress into a simple
   status string to pass to js.
 - Use Progress.to_js_detail_str() to convert a progress into a more detailed
   string to pass to js.

In particular, these functions have a canonical handing of None.

For most subclassing needs, you should only need to reimplement
frac() and __str__().
'''

import numbers


class Progress(object):
    '''Represents a progress of a/b (a out of b done)

    a and b must be numeric, but not necessarily integer, with
    0 <= a <= b and b > 0.

    Progress can only represent Progress for modules where that makes sense.  Other
    modules (e.g. html) should return None from get_progress().

    TODO: add tag for module type?  Would allow for smarter merging.
    '''

    def __init__(self, a, b):
        '''Construct a Progress object.  a and b must be numbers, and must have
              0 <= a <= b and b > 0
        '''

        # Want to do all checking at construction time, so explicitly check types
        if not (isinstance(a, numbers.Number) and
                isinstance(b, numbers.Number)):
            raise TypeError('a and b must be numbers.  Passed {0}/{1}'.format(a, b))

        if a > b:
            a = b

        if a < 0:
            a = 0

        if b <= 0:
            raise ValueError('fraction a/b = {0}/{1} must have b > 0'.format(a, b))

        self._a = a
        self._b = b

    def frac(self):
        ''' Return tuple (a,b) representing progress of a/b'''
        return (self._a, self._b)

    def percent(self):
        ''' Returns a percentage progress as a float between 0 and 100.

        subclassing note: implemented in terms of frac(), assumes sanity
        checking is done at construction time.
        '''
        (a, b) = self.frac()
        return 100.0 * a / b

    def started(self):
        ''' Returns True if fractional progress is greater than 0.

        subclassing note: implemented in terms of frac(), assumes sanity
        checking is done at construction time.
        '''
        return self.frac()[0] > 0

    def inprogress(self):
        ''' Returns True if fractional progress is strictly between 0 and 1.

        subclassing note: implemented in terms of frac(), assumes sanity
        checking is done at construction time.
        '''
        (a, b) = self.frac()
        return a > 0 and a < b

    def done(self):
        ''' Return True if this represents done.

        subclassing note: implemented in terms of frac(), assumes sanity
        checking is done at construction time.
        '''
        (a, b) = self.frac()
        return a == b

    def ternary_str(self):
        ''' Return a string version of this progress: either
           "none", "in_progress", or "done".

        subclassing note: implemented in terms of frac()
        '''
        (a, b) = self.frac()
        if a == 0:
            return "none"
        if a < b:
            return "in_progress"
        return "done"

    def __eq__(self, other):
        ''' Two Progress objects are equal if they have identical values.
        Implemented in terms of frac()'''
        if not isinstance(other, Progress):
            return False
        (a, b) = self.frac()
        (a2, b2) = other.frac()
        return a == a2 and b == b2

    def __ne__(self, other):
        ''' The opposite of equal'''
        return not self.__eq__(other)

    def __str__(self):
        ''' Return a string representation of this string.

        subclassing note: implemented in terms of frac().
        '''
        (a, b) = self.frac()
        return "{0}/{1}".format(a, b)

    @staticmethod
    def add_counts(a, b):
        '''Add two progress indicators, assuming that each represents items done:
        (a / b) + (c / d) = (a + c) / (b + d).
        If either is None, returns the other.
        '''
        if a is None:
            return b
        if b is None:
            return a
        # get numerators + denominators
        (n, d) = a.frac()
        (n2, d2) = b.frac()
        return Progress(n + n2, d + d2)

    @staticmethod
    def to_js_status_str(progress):
        '''
        Return the "status string" version of the passed Progress
        object that should be passed to js.  Use this function when
        sending Progress objects to js to limit dependencies.
        '''
        if progress is None:
            return "NA"
        return progress.ternary_str()

    @staticmethod
    def to_js_detail_str(progress):
        '''
        Return the "detail string" version of the passed Progress
        object that should be passed to js.  Use this function when
        passing Progress objects to js to limit dependencies.
        '''
        if progress is None:
            return "NA"
        return str(progress)
