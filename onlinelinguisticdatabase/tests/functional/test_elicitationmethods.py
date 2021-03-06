# Copyright 2013 Joel Dunham
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
import simplejson as json
from time import sleep
from nose.tools import nottest
from onlinelinguisticdatabase.tests import TestController, url
import onlinelinguisticdatabase.model as model
from onlinelinguisticdatabase.model.meta import Session
import onlinelinguisticdatabase.lib.helpers as h
from onlinelinguisticdatabase.model import ElicitationMethod

log = logging.getLogger(__name__)

################################################################################
# Functions for creating & retrieving test data
################################################################################

class TestElicitationMethodsController(TestController):

    @nottest
    def test_index(self):
        """Tests that GET /elicitationmethods returns an array of all elicitation methods and that order_by and pagination parameters work correctly."""

        # Add 100 elicitation methods.
        def create_elicitation_method_from_index(index):
            elicitation_method = model.ElicitationMethod()
            elicitation_method.name = u'em%d' % index
            elicitation_method.description = u'description %d' % index
            return elicitation_method
        elicitation_methods = [create_elicitation_method_from_index(i) for i in range(1, 101)]
        Session.add_all(elicitation_methods)
        Session.commit()
        elicitation_methods = h.get_elicitation_methods(True)
        elicitation_methods_count = len(elicitation_methods)

        # Test that GET /elicitationmethods gives us all of the elicitation methods.
        response = self.app.get(url('elicitationmethods'), headers=self.json_headers,
                                extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert len(resp) == elicitation_methods_count
        assert resp[0]['name'] == u'em1'
        assert resp[0]['id'] == elicitation_methods[0].id
        assert response.content_type == 'application/json'

        # Test the paginator GET params.
        paginator = {'items_per_page': 23, 'page': 3}
        response = self.app.get(url('elicitationmethods'), paginator, headers=self.json_headers,
                                extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert len(resp['items']) == 23
        assert resp['items'][0]['name'] == elicitation_methods[46].name

        # Test the order_by GET params.
        order_by_params = {'order_by_model': 'ElicitationMethod', 'order_by_attribute': 'name',
                     'order_by_direction': 'desc'}
        response = self.app.get(url('elicitationmethods'), order_by_params,
                        headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        result_set = sorted([em.name for em in elicitation_methods], reverse=True)
        assert result_set == [em['name'] for em in resp]

        # Test the order_by *with* paginator.
        params = {'order_by_model': 'ElicitationMethod', 'order_by_attribute': 'name',
                     'order_by_direction': 'desc', 'items_per_page': 23, 'page': 3}
        response = self.app.get(url('elicitationmethods'), params,
                        headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert result_set[46] == resp['items'][0]['name']

        # Expect a 400 error when the order_by_direction param is invalid
        order_by_params = {'order_by_model': 'ElicitationMethod', 'order_by_attribute': 'name',
                     'order_by_direction': 'descending'}
        response = self.app.get(url('elicitationmethods'), order_by_params, status=400,
            headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert resp['errors']['order_by_direction'] == u"Value must be one of: asc; desc (not u'descending')"
        assert response.content_type == 'application/json'

        # Expect the default BY id ASCENDING ordering when the order_by_model/Attribute
        # param is invalid.
        order_by_params = {'order_by_model': 'ElicitationMethodist', 'order_by_attribute': 'nominal',
                     'order_by_direction': 'desc'}
        response = self.app.get(url('elicitationmethods'), order_by_params,
            headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert resp[0]['id'] == elicitation_methods[0].id

        # Expect a 400 error when the paginator GET params are empty
        # or are integers less than 1
        paginator = {'items_per_page': u'a', 'page': u''}
        response = self.app.get(url('elicitationmethods'), paginator, headers=self.json_headers,
                                extra_environ=self.extra_environ_view, status=400)
        resp = json.loads(response.body)
        assert resp['errors']['items_per_page'] == u'Please enter an integer value'
        assert resp['errors']['page'] == u'Please enter a value'

        paginator = {'items_per_page': 0, 'page': -1}
        response = self.app.get(url('elicitationmethods'), paginator, headers=self.json_headers,
                                extra_environ=self.extra_environ_view, status=400)
        resp = json.loads(response.body)
        assert resp['errors']['items_per_page'] == u'Please enter a number that is 1 or greater'
        assert resp['errors']['page'] == u'Please enter a number that is 1 or greater'

    @nottest
    def test_create(self):
        """Tests that POST /elicitationmethods creates a new elicitation method
        or returns an appropriate error if the input is invalid.
        """

        original_EM_count = Session.query(ElicitationMethod).count()

        # Create a valid one
        params = json.dumps({'name': u'em', 'description': u'Described.'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        new_EM_count = Session.query(ElicitationMethod).count()
        assert new_EM_count == original_EM_count + 1
        assert resp['name'] == u'em'
        assert resp['description'] == u'Described.'
        assert response.content_type == 'application/json'

        # Invalid because name is not unique
        params = json.dumps({'name': u'em', 'description': u'Described.'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers, self.extra_environ_admin, status=400)
        resp = json.loads(response.body)
        assert resp['errors']['name'] == u'The submitted value for ElicitationMethod.name is not unique.'
        assert response.content_type == 'application/json'

        # Invalid because name is empty
        params = json.dumps({'name': u'', 'description': u'Described.'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers, self.extra_environ_admin, status=400)
        resp = json.loads(response.body)
        assert resp['errors']['name'] == u'Please enter a value'

        # Invalid because name is too long
        params = json.dumps({'name': u'name' * 400, 'description': u'Described.'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers, self.extra_environ_admin, status=400)
        resp = json.loads(response.body)
        assert resp['errors']['name'] == u'Enter a value not more than 255 characters long'

    @nottest
    def test_new(self):
        """Tests that GET /elicitationmethods/new returns an empty JSON object."""
        response = self.app.get(url('new_elicitationmethod'), headers=self.json_headers,
                                extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        assert resp == {}
        assert response.content_type == 'application/json'

    @nottest
    def test_update(self):
        """Tests that PUT /elicitationmethods/id updates the elicitationmethod with id=id."""

        # Create an elicitation method to update.
        params = json.dumps({'name': u'name', 'description': u'description'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        elicitation_method_count = Session.query(ElicitationMethod).count()
        elicitation_method_id = resp['id']
        original_datetime_modified = resp['datetime_modified']

        # Update the elicitation method
        sleep(1)    # sleep for a second to ensure that MySQL registers a different datetime_modified for the update
        params = json.dumps({'name': u'name', 'description': u'More content-ful description.'})
        response = self.app.put(url('elicitationmethod', id=elicitation_method_id), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        datetime_modified = resp['datetime_modified']
        new_elicitation_method_count = Session.query(ElicitationMethod).count()
        assert elicitation_method_count == new_elicitation_method_count
        assert datetime_modified != original_datetime_modified
        assert response.content_type == 'application/json'

        # Attempt an update with no new input and expect to fail
        sleep(1)    # sleep for a second to ensure that MySQL could register a different datetime_modified for the update
        response = self.app.put(url('elicitationmethod', id=elicitation_method_id), params, self.json_headers,
                                 self.extra_environ_admin, status=400)
        resp = json.loads(response.body)
        elicitation_method_count = new_elicitation_method_count
        new_elicitation_method_count = Session.query(ElicitationMethod).count()
        our_EM_datetime_modified = Session.query(ElicitationMethod).get(elicitation_method_id).datetime_modified
        assert our_EM_datetime_modified.isoformat() == datetime_modified
        assert elicitation_method_count == new_elicitation_method_count
        assert resp['error'] == u'The update request failed because the submitted data were not new.'
        assert response.content_type == 'application/json'

    @nottest
    def test_delete(self):
        """Tests that DELETE /elicitationmethods/id deletes the elicitation_method with id=id."""

        # Create an elicitation method to delete.
        params = json.dumps({'name': u'name', 'description': u'description'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        elicitation_method_count = Session.query(ElicitationMethod).count()
        elicitation_method_id = resp['id']

        # Now delete the elicitation method
        response = self.app.delete(url('elicitationmethod', id=elicitation_method_id), headers=self.json_headers,
            extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        new_elicitation_method_count = Session.query(ElicitationMethod).count()
        assert new_elicitation_method_count == elicitation_method_count - 1
        assert resp['id'] == elicitation_method_id
        assert response.content_type == 'application/json'

        # Trying to get the deleted elicitation method from the db should return None
        deleted_elicitation_method = Session.query(ElicitationMethod).get(elicitation_method_id)
        assert deleted_elicitation_method == None

        # Delete with an invalid id
        id = 9999999999999
        response = self.app.delete(url('elicitationmethod', id=id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin,
            status=404)
        assert u'There is no elicitation method with id %s' % id in json.loads(response.body)['error']
        assert response.content_type == 'application/json'

        # Delete without an id
        response = self.app.delete(url('elicitationmethod', id=''), status=404,
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert json.loads(response.body)['error'] == 'The resource could not be found.'

    @nottest
    def test_show(self):
        """Tests that GET /elicitationmethods/id returns the elicitation method with id=id or an appropriate error."""

        # Create an elicitation method to show.
        params = json.dumps({'name': u'name', 'description': u'description'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        elicitation_method_id = resp['id']

        # Try to get a elicitation_method using an invalid id
        id = 100000000000
        response = self.app.get(url('elicitationmethod', id=id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin,
            status=404)
        resp = json.loads(response.body)
        assert u'There is no elicitation method with id %s' % id in json.loads(response.body)['error']
        assert response.content_type == 'application/json'

        # No id
        response = self.app.get(url('elicitationmethod', id=''), status=404,
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert json.loads(response.body)['error'] == 'The resource could not be found.'

        # Valid id
        response = self.app.get(url('elicitationmethod', id=elicitation_method_id), headers=self.json_headers,
                                extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp['name'] == u'name'
        assert resp['description'] == u'description'
        assert response.content_type == 'application/json'

    @nottest
    def test_edit(self):
        """Tests that GET /elicitationmethods/id/edit returns a JSON object of data necessary to edit the elicitation method with id=id.

        The JSON object is of the form {'elicitation_method': {...}, 'data': {...}} or
        {'error': '...'} (with a 404 status code) depending on whether the id is
        valid or invalid/unspecified, respectively.
        """

        # Create an elicitation method to edit.
        params = json.dumps({'name': u'name', 'description': u'description'})
        response = self.app.post(url('elicitationmethods'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        elicitation_method_id = resp['id']

        # Not logged in: expect 401 Unauthorized
        response = self.app.get(url('edit_elicitationmethod', id=elicitation_method_id), status=401)
        resp = json.loads(response.body)
        assert resp['error'] == u'Authentication is required to access this resource.'
        assert response.content_type == 'application/json'

        # Invalid id
        id = 9876544
        response = self.app.get(url('edit_elicitationmethod', id=id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin,
            status=404)
        assert u'There is no elicitation method with id %s' % id in json.loads(response.body)['error']
        assert response.content_type == 'application/json'

        # No id
        response = self.app.get(url('edit_elicitationmethod', id=''), status=404,
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert json.loads(response.body)['error'] == \
            'The resource could not be found.'

        # Valid id
        response = self.app.get(url('edit_elicitationmethod', id=elicitation_method_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp['elicitation_method']['name'] == u'name'
        assert resp['data'] == {}
        assert response.content_type == 'application/json'
