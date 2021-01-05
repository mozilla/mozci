# -*- coding: utf-8 -*-
import functools


class memoize(dict):
    """A decorator to memoize the results of function calls depending
    on its arguments.
    Both functions and instance methods are handled, although in the
    instance method case, the results are cache in the instance itself.
    """

    def __init__(self, func):
        self.func = func
        functools.update_wrapper(self, func)

    def __call__(self, *args):
        if args not in self:
            self[args] = self.func(*args)
        return self[args]

    def method_call(self, instance, *args, **kwargs):
        name = "_%s" % self.func.__name__
        if not hasattr(instance, name):
            setattr(instance, name, {})
        cache = getattr(instance, name)
        kwargs_tuple = tuple(kwargs.items())
        if (args, kwargs_tuple) not in cache:
            cache[(args, kwargs_tuple)] = self.func(instance, *args, **kwargs)
        return cache[(args, kwargs_tuple)]

    def __get__(self, instance, cls):
        return functools.update_wrapper(
            functools.partial(self.method_call, instance), self.func
        )


class memoized_property(object):
    """A specialized version of the memoize decorator that works for
    class instance properties.
    """

    def __init__(self, func):
        self.func = func
        functools.update_wrapper(self, func)

    def __get__(self, instance, cls):
        name = "_%s" % self.func.__name__
        if not hasattr(instance, name):
            setattr(instance, name, self.func(instance))
        return getattr(instance, name)
