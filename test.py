# -*- coding: utf-8 -*-

from mozci.push import Push

p = Push(["4185629111d323484d1f74a667d57145616203b7"], "mozilla-central")
print(p.classify())
