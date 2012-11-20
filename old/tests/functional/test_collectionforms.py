from old.tests import *
from nose.tools import nottest

class TestCollectionformsController(TestController):

    @nottest
    def test_index(self):
        response = self.app.get(url('collectionforms'))
        # Test response...

    @nottest
    def test_create(self):
        response = self.app.post(url('collectionforms'))

    @nottest
    def test_new(self):
        response = self.app.get(url('new_collectionform'))

    @nottest
    def test_update(self):
        response = self.app.put(url('collectionform', id=1))

    @nottest
    def test_delete(self):
        response = self.app.delete(url('collectionform', id=1))

    @nottest
    def test_show(self):
        response = self.app.get(url('collectionform', id=1))

    @nottest
    def test_edit(self):
        response = self.app.get(url('edit_collectionform', id=1))