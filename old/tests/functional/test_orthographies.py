from old.tests import *
from nose.tools import nottest

class TestOrthographiesController(TestController):

    @nottest
    def test_index(self):
        response = self.app.get(url('orthographies'))
        # Test response...

    @nottest
    def test_create(self):
        response = self.app.post(url('orthographies'))

    @nottest
    def test_new(self):
        response = self.app.get(url('new_orthography'))

    @nottest
    def test_update(self):
        response = self.app.put(url('orthography', id=1))

    @nottest
    def test_delete(self):
        response = self.app.delete(url('orthography', id=1))

    @nottest
    def test_show(self):
        response = self.app.get(url('orthography', id=1))

    @nottest
    def test_edit(self):
        response = self.app.get(url('edit_orthography', id=1))
