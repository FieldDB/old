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
import os
import sys
import codecs
from shutil import copyfileobj
from time import time
import simplejson as json
from time import sleep
from nose.tools import nottest
from sqlalchemy.sql import desc
from onlinelinguisticdatabase.tests import TestController, url
import onlinelinguisticdatabase.model as model
from onlinelinguisticdatabase.model.meta import Session
from subprocess import call
import onlinelinguisticdatabase.lib.helpers as h
from onlinelinguisticdatabase.model import Morphology, MorphologyBackup

log = logging.getLogger(__name__)


def pretty_parses(parses):
    result = []
    for parse in parses:
        tmp = parse.split('-')
        tmp = [x.split(u'\u2980') for x in tmp]
        tmp = zip(*tmp)
        result.append('%s %s' % (u'-'.join(tmp[0]), u'-'.join(tmp[1])))
    return result

class TestMorphologicalparsersController(TestController):
    """Tests the morphologicalparsers controller.  WARNING: the tests herein are pretty messy.  The higher 
    ordered tests will fail if the previous tests have not been run.

    """

    def __init__(self, *args, **kwargs):
        TestController.__init__(self, *args, **kwargs)
        self.blackfoot_phonology_script = h.normalize(
            codecs.open(self.test_phonology_script_path, 'r', 'utf8').read())

    def tearDown(self):
        pass

    def create_form(self, tr, mb, mg, tl, cat):
        params = self.form_create_params.copy()
        params.update({'transcription': tr, 'morpheme_break': mb, 'morpheme_gloss': mg,
            'translations': [{'transcription': tl, 'grammaticality': u''}], 'syntactic_category': cat})
        params = json.dumps(params)
        self.app.post(url('forms'), params, self.json_headers, self.extra_environ_admin)

    def human_readable_seconds(self, seconds):
        return u'%02dm%02ds' % (seconds / 60, seconds % 60)

    #@nottest
    def test(self):
        """General purpose test for morphological parsers.
        """

        # Create the default application settings -- note that we have only one morpheme delimiter.
        # This is relevant to the morphemic language model.
        application_settings = h.generate_default_application_settings()
        application_settings.morpheme_delimiters = u'-'
        Session.add(application_settings)
        Session.commit()

        # Create some syntactic categories
        cats = {
            'N': model.SyntacticCategory(name=u'N'),
            'V': model.SyntacticCategory(name=u'V'),
            'AGR': model.SyntacticCategory(name=u'AGR'),
            'PHI': model.SyntacticCategory(name=u'PHI'),
            'S': model.SyntacticCategory(name=u'S'),
            'D': model.SyntacticCategory(name=u'D')
        }
        Session.add_all(cats.values())
        Session.commit()
        cats = dict([(k, v.id) for k, v in cats.iteritems()])

        dataset = (
            ('chien', 'chien', 'dog', 'dog', cats['N']),
            ('chat', 'chat', 'cat', 'cat', cats['N']),
            ('oiseau', 'oiseau', 'bird', 'bird', cats['N']),
            ('cheval', 'cheval', 'horse', 'horse', cats['N']),
            ('vache', 'vache', 'cow', 'cow', cats['N']),
            ('grenouille', 'grenouille', 'frog', 'frog', cats['N']),
            ('tortue', 'tortue', 'turtle', 'turtle', cats['N']),
            ('fourmi', 'fourmi', 'ant', 'ant', cats['N']),
            ('poule!t', 'poule!t', 'chicken', 'chicken', cats['N']), # note the ! which is a foma reserved symbol
            (u'be\u0301casse', u'be\u0301casse', 'woodcock', 'woodcock', cats['N']),

            ('parle', 'parle', 'speak', 'speak', cats['V']),
            ('grimpe', 'grimpe', 'climb', 'climb', cats['V']),
            ('nage', 'nage', 'swim', 'swim', cats['V']),
            ('tombe', 'tombe', 'fall', 'fall', cats['V']),

            ('le', 'le', 'the', 'the', cats['D']),
            ('la', 'la', 'the', 'the', cats['D']),

            ('s', 's', 'PL', 'plural', cats['PHI']),

            ('ait', 'ait', '3SG.IMPV', 'third person singular imperfective', cats['AGR']),
            ('aient', 'aient', '3PL.IMPV', 'third person plural imperfective', cats['AGR']),

            ('Les chats nageaient.', 'le-s chat-s nage-aient', 'the-PL cat-PL swim-3PL.IMPV', 'The cats were swimming.', cats['S']),
            ('La tortue parlait', 'la tortue parle-ait', 'the turtle speak-3SG.IMPV', 'The turtle was speaking.', cats['S'])
        )

        for tuple_ in dataset:
            self.create_form(*map(unicode, tuple_))

        # Create a form search model that returns lexical items (will be used to create the lexicon corpus)
        query = {'filter': ['Form', 'syntactic_category', 'name', 'in', [u'N', u'V', u'AGR', u'PHI', u'D']]}
        params = self.form_search_create_params.copy()
        params.update({
            'name': u'Find morphemes',
            'search': query
        })
        params = json.dumps(params)
        response = self.app.post(url('formsearches'), params, self.json_headers, self.extra_environ_admin)
        lexicon_form_search_id = json.loads(response.body)['id']

        # Create the lexicon corpus
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of lexical items',
            'form_search': lexicon_form_search_id
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        lexicon_corpus_id = json.loads(response.body)['id']

        # Create a form search model that returns sentences (will be used to create the rules corpus)
        query = {'filter': ['Form', 'syntactic_category', 'name', '=', u'S']}
        params = self.form_search_create_params.copy()
        params.update({
            'name': u'Find sentences',
            'description': u'Returns all sentential forms',
            'search': query
        })
        params = json.dumps(params)
        response = self.app.post(url('formsearches'), params, self.json_headers, self.extra_environ_admin)
        rules_form_search_id = json.loads(response.body)['id']

        # Create the rules corpus
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of sentences',
            'form_search': rules_form_search_id
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        rules_corpus_id = json.loads(response.body)['id']

        # Create a morphology using the lexicon and rules corpora
        name = u'Morphology of a very small subset of french'
        params = self.morphology_create_params.copy()
        params.update({
            'name': name,
            'lexicon_corpus': lexicon_corpus_id,
            'rules_corpus': rules_corpus_id,
            'script_type': 'regex'
        })
        params = json.dumps(params)
        response = self.app.post(url('morphologies'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morphology_id = resp['id']
        assert resp['name'] == name
        assert resp['script_type'] == u'regex'

        # If foma is not installed, make sure the error message is being returned
        # and exit the test.
        if not h.foma_installed(force_check=True):
            response = self.app.put(url(controller='morphologies', action='generate_and_compile',
                        id=morphology_id), headers=self.json_headers,
                        extra_environ=self.extra_environ_contrib, status=400)
            resp = json.loads(response.body)
            assert resp['error'] == u'Foma and flookup are not installed.'
            return

        # Compile the morphology's script
        response = self.app.put(url(controller='morphologies', action='generate_and_compile',
                    id=morphology_id), headers=self.json_headers,
                    extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        compile_attempt = resp['compile_attempt']

        # Poll ``GET /morphologies/morphology_id`` until ``compile_attempt`` has changed.
        while True:
            response = self.app.get(url('morphology', id=morphology_id),
                        headers=self.json_headers, extra_environ=self.extra_environ_contrib)
            resp = json.loads(response.body)
            if compile_attempt != resp['compile_attempt']:
                log.debug('Compile attempt for morphology %d has terminated.' % morphology_id)
                break
            else:
                log.debug('Waiting for morphology %d to compile ...' % morphology_id)
            sleep(1)
        response = self.app.get(url('morphology', id=morphology_id), params={'script': u'1', 'lexicon': u'1'},
                    headers=self.json_headers, extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        morphology_dir = os.path.join(self.morphologies_path, 'morphology_%d' % morphology_id)
        morphology_binary_filename = 'morphology_%d.foma' % morphology_id
        morphology_dir_contents = os.listdir(morphology_dir)
        morphology_script_path = os.path.join(morphology_dir, 'morphology_%d.script' % morphology_id)
        morphology_script = codecs.open(morphology_script_path, mode='r', encoding='utf8').read()
        assert u'define morphology' in morphology_script
        assert u'(NCat)' in morphology_script # cf. tortue
        assert u'(DCat)' in morphology_script # cf. la
        assert u'(NCat "-" PHICat)' in morphology_script # cf. chien-s
        assert u'(DCat "-" PHICat)' in morphology_script # cf. le-s
        assert u'(VCat "-" AGRCat)' in morphology_script # cf. nage-aient, parle-ait
        assert u'c h a t "%scat":0' % h.rare_delimiter in morphology_script # cf. extract_morphemes_from_rules_corpus = False and chat's exclusion from the lexicon corpus
        assert u'c h i e n "%sdog":0' % h.rare_delimiter in morphology_script
        assert u'b e \u0301 c a s s e "%swoodcock":0' % h.rare_delimiter in morphology_script
        assert resp['compile_succeeded'] == True
        assert resp['compile_message'] == u'Compilation process terminated successfully and new binary file was written.'
        assert morphology_binary_filename in morphology_dir_contents
        assert resp['modifier']['role'] == u'contributor'
        rules = resp['rules_generated']
        assert u'D' in rules # cf. le
        assert u'N' in rules # cf. tortue
        assert u'D-PHI' in rules # cf. le-s
        assert u'N-PHI' in rules # cf. chien-s
        assert u'V-AGR' in rules # cf. nage-aient, parle-ait
        assert 'lexicon' in resp
        assert 'script' in resp
        assert resp['script'] == morphology_script
        assert [u'chat', u'cat'] in resp['lexicon']['N']
        assert [u'chien', u'dog'] in resp['lexicon']['N']

        # Test GET /morphologies/1?script=1&lexicon=1 and make sure the script and lexicon are returned
        response = self.app.get(url('morphology', id=morphology_id), params={'script': u'1', 'lexicon': u'1'},
                    headers=self.json_headers, extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        assert resp['script'] == morphology_script
        lexicon = resp['lexicon']
        assert ['s', 'PL'] in lexicon['PHI']
        assert ['oiseau', 'bird'] in lexicon['N']
        assert ['aient', '3PL.IMPV'] in lexicon['AGR']
        assert ['la', 'the'] in lexicon['D']
        assert ['nage', 'swim'] in lexicon['V']

        # Create a very simple French phonology
        script = u'''
define eDrop e -> 0 || _ "-" a;
define breakDrop "-" -> 0;
define phonology eDrop .o. breakDrop;
        '''
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Phonology',
            'description': u'Covers a lot of the data.',
            'script': script
        })
        params = json.dumps(params)
        response = self.app.post(url('phonologies'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        phonology_id = resp['id']

        # Create a morpheme language model
        name = u'Morpheme language model'
        params = self.morpheme_language_model_create_params.copy()
        params.update({
            'name': name,
            'corpus': rules_corpus_id,
            'toolkit': 'mitlm'
        })
        params = json.dumps(params)
        response = self.app.post(url('morphemelanguagemodels'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morpheme_language_model_id = resp['id']
        assert resp['name'] == name
        assert resp['toolkit'] == u'mitlm'
        assert resp['order'] == 3
        assert resp['smoothing'] == u'' # The ModKN smoothing algorithm is the implicit default with MITLM

        # Generate the files of the language model
        response = self.app.put(url(controller='morphemelanguagemodels', action='generate', id=morpheme_language_model_id),
            {}, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        lm_generate_attempt = resp['generate_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphemelanguagemodel', id=morpheme_language_model_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', lm_generate_attempt, log, wait=1, vocal=False)
        assert resp['generate_message'] == u'Language model successfully generated.'

        # Create the morphological parser

        # Create a morphological parser for toy french
        params = self.morphological_parser_create_params.copy()
        params.update({
            'name': u'Morphological parser for toy French',
            'phonology': phonology_id,
            'morphology': morphology_id,
            'language_model': morpheme_language_model_id
        })
        params = json.dumps(params)
        response = self.app.post(url('morphologicalparsers'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_id = resp['id']

        # Generate the parser's morphophonology FST and compile it.
        response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
            id=morphological_parser_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_compile_attempt = resp['compile_attempt']

        # Poll ``GET /morphologicalparsers/morphological_parser_id`` until ``compile_attempt`` has changed.
        while True:
            response = self.app.get(url('morphologicalparser', id=morphological_parser_id),
                        headers=self.json_headers, extra_environ=self.extra_environ_contrib)
            resp = json.loads(response.body)
            if morphological_parser_compile_attempt != resp['compile_attempt']:
                log.debug('Compile attempt for morphological parser %d has terminated.' % morphological_parser_id)
                break
            else:
                log.debug('Waiting for morphological parser %d to compile ...' % morphological_parser_id)
            sleep(1)

        # Test applyup on the mophological parser's morphophonology FST
        transcription1 = u'tombait'
        transcription1_correct_parse = u'tombe%sfall-ait%s3SG.IMPV' % (h.rare_delimiter, h.rare_delimiter)
        transcription2 = u'tombeait'
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_correct_parse in resp[transcription1]
        assert len(resp[transcription1]) == 1
        assert resp[transcription2] == []

        # Test how well the morphological parser parses some test words.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        # There is only one possible parse for transcription 1 -- it is de facto the most probable
        assert resp[transcription1] == transcription1_correct_parse

    #@nottest
    def test_i_large_datasets(self):
        """Tests that morphological parser functionality works with large datasets.

        .. note::

            This test only works if MySQL is being used as the RDBMS for the test
            *and* there is a file in 
            ``onlinelinguisticdatabase/onlinelinguisticdatabase/tests/data/datasets/``
            that is a MySQL dump file of a valid OLD database.  The name of this file
            can be configured by setting the ``old_dump_file`` variable.  Note that no
            such dump file is provided with the OLD source since the file used by the
            developer contains data that cannot be publicly shared.

        """

        # If foma is not installed, exit.
        if not h.foma_installed(force_check=True):
            return

        # Configuration

        # The ``old_dump_file`` variable holds the name of a MySQL dump file in /tests/data/datasets
        # that will be used to populate the database.
        old_dump_file = 'blaold.sql'
        backup_dump_file = 'old_test_dump.sql'

        # The ``precompiled_morphophonology`` variable holds the name of a compiled foma FST that
        # maps surface representations to sequences of morphemes.  A file with this name should be
        # present in /tests/data/morphophonologies or else the variable should be set to None.
        pregenerated_morphophonology = 'blaold_morphophonology.script'
        precompiled_morphophonology = 'blaold_morphophonology.foma'

        # Here we load a whole database from the mysqpl dump file specified in ``tests/data/datasets/<old_dump_file>``.
        old_dump_file_path = os.path.join(self.test_datasets_path, old_dump_file)
        backup_dump_file_path = os.path.join(self.test_datasets_path, backup_dump_file)
        tmp_script_path = os.path.join(self.test_datasets_path, 'tmp.sh')
        if not os.path.isfile(old_dump_file_path):
            return
        config = h.get_config(config_filename='test.ini')
        SQLAlchemyURL = config['sqlalchemy.url']
        if not SQLAlchemyURL.split(':')[0] == 'mysql':
            return
        rdbms, username, password, db_name = SQLAlchemyURL.split(':')
        username = username[2:]
        password = password.split('@')[0]
        db_name = db_name.split('/')[-1]
        # First dump the existing database so we can load it later.
        with open(tmp_script_path, 'w') as tmpscript:
            tmpscript.write('#!/bin/sh\nmysqldump -u %s -p%s %s > %s' % (username, password, db_name, backup_dump_file_path))
        os.chmod(tmp_script_path, 0744)
        with open(os.devnull, "w") as fnull:
            call([tmp_script_path], stdout=fnull, stderr=fnull)
        # Now load the dump file of the large database (from old_dump_file)
        with open(tmp_script_path, 'w') as tmpscript:
            tmpscript.write('#!/bin/sh\nmysql -u %s -p%s %s < %s' % (username, password, db_name, old_dump_file_path))
        with open(os.devnull, "w") as fnull:
            call([tmp_script_path], stdout=fnull, stderr=fnull)

        # Recreate the default users that the loaded dump file deleted
        administrator = h.generate_default_administrator()
        contributor = h.generate_default_contributor()
        viewer = h.generate_default_viewer()
        Session.add_all([administrator, contributor, viewer])
        Session.commit()

        ################################################################################
        # PHONOLOGY
        ################################################################################

        # Create a Blackfoot phonology with the test phonology script
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Blackfoot Phonology',
            'description': u'The phonological rules of Frantz (1997) as FSTs',
            'script': self.blackfoot_phonology_script
        })
        params = json.dumps(params)
        response = self.app.post(url('phonologies'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        phonology_id = resp['id']

        ################################################################################
        # MORPHOLOGY
        ################################################################################

        # Create a lexicon form search and corpus
        # The code below constructs a query that finds a (large) subset of the Blackfoot morphemes.
        # Notes for future morphology creators:
        # 1. the "oth" category is a mess: detangle the nominalizer, inchoative, transitive suffixes, etc. from
        #    one another and from the numerals and temporal modifiers -- ugh!
        # 2. the "pro" category" is also a mess: clearly pronoun-forming iisto does not have the same distribution 
        #    as the verbal suffixes aiksi and aistsi!  And oht, the LING/means thing, is different again...
        # 3. hkayi, that thing at the end of demonstratives, is not agra, what is it? ...
        # 4. the dim category contains only 'sst' 'DIM' and is not used in any forms ...
        lexical_category_names = ['nan', 'nin', 'nar', 'nir', 'vai', 'vii', 'vta', 'vti', 'vrt', 'adt',
            'drt', 'prev', 'med', 'fin', 'oth', 'o', 'und', 'pro', 'asp', 'ten', 'mod', 'agra', 'agrb', 'thm', 'whq',
            'num', 'stp', 'PN']
        durative_morpheme = 15717
        hkayi_morpheme = 23429
        query = {'filter': ['and', [['Form', 'syntactic_category', 'name', 'in', lexical_category_names],
                                    ['not', ['Form', 'morpheme_break', 'regex', '[ -]']],
                                    ['not', ['Form', 'id', 'in', [durative_morpheme, hkayi_morpheme]]],
                                    ['not', ['Form', 'grammaticality', '=', '*']]
                                   ]]}
        smaller_query_for_rapid_testing = {'filter': ['and', [['Form', 'id', '<', 1000],
                                    ['Form', 'syntactic_category', 'name', 'in', lexical_category_names]]]}
        params = self.form_search_create_params.copy()
        params.update({
            'name': u'Blackfoot morphemes',
            'search': query
        })
        params = json.dumps(params)
        response = self.app.post(url('formsearches'), params, self.json_headers, self.extra_environ_admin)
        lexicon_form_search_id = json.loads(response.body)['id']
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of Blackfoot morphemes',
            'form_search': lexicon_form_search_id
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        lexicon_corpus_id = json.loads(response.body)['id']

        # Create a rules corpus

        # Create a corpus of forms containing words -- to be used to estimate ngram probabilities
        # The goal here is to exclude things that look like words but are not really words, i.e., 
        # morphemes; as a heuristic we search for grammatical forms categorized as 'sent' or whose
        # transcription value contains a space or a dash.
        query = {'filter': ['and', [['or', [['Form', 'syntactic_category', 'name', '=', u'sent'],
                                            ['Form', 'morpheme_break', 'like', '% %'],
                                            ['Form', 'morpheme_break', 'like', '%-%']]],
                                   ['Form', 'syntactic_category_string', '!=', None],
                                   ['Form', 'grammaticality', '=', '']]]}
        params = self.form_search_create_params.copy()
        params.update({
            'name': u'Find Blackfoot sentences',
            'description': u'Returns all forms containing words',
            'search': query
        })
        params = json.dumps(params)
        response = self.app.post(url('formsearches'), params, self.json_headers, self.extra_environ_admin)
        rules_form_search_id = json.loads(response.body)['id']
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of Blackfoot sentences',
            'form_search': rules_form_search_id
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        rules_corpus_id = json.loads(response.body)['id']

        # Now we reduce the number of category-based word-formation rules by removing all such
        # rules implicit in the rules corpus that have fewer than two exemplar tokens.

        # Get the category sequence types of all of the words in the rules corpus ordered by their counts, minus
        # those with fewer than ``minimum_token_count`` counts.
        minimum_token_count = 2
        params = {'minimum_token_count': minimum_token_count}
        response = self.app.get(url(controller='corpora', action='get_word_category_sequences', id=rules_corpus_id),
                params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)

        word_category_sequences = u' '.join([word_category_sequence for word_category_sequence, ids in resp])
        #word_category_sequences = u'agra-vai vai-agrb'

        # Now create a morphology using the lexicon and rules defined by word_category_sequences
        name = u'Morphology of Blackfoot'
        params = self.morphology_create_params.copy()
        params.update({
            'name': name,
            'lexicon_corpus': lexicon_corpus_id,
            'rules': word_category_sequences,
            'script_type': u'lexc',
            'extract_morphemes_from_rules_corpus': False
        })
        params = json.dumps(params)
        response = self.app.post(url('morphologies'), params, self.json_headers, self.extra_environ_admin_appset)
        resp = json.loads(response.body)
        morphology_id = resp['id']
        assert resp['name'] == name
        assert resp['script_type'] == u'lexc'

        # Generate the morphology's script without compiling it.
        response = self.app.put(url(controller='morphologies', action='generate',
                    id=morphology_id), headers=self.json_headers,
                    extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        generate_attempt = resp['generate_attempt']

        # Poll ``GET /morphologies/morphology_id`` until ``generate_attempt`` has changed.
        seconds_elapsed = 0
        wait = 2
        while True:
            response = self.app.get(url('morphology', id=morphology_id),
                        headers=self.json_headers, extra_environ=self.extra_environ_contrib)
            resp = json.loads(response.body)
            if generate_attempt != resp['generate_attempt']:
                log.debug('Generate attempt for morphology %d has terminated.' % morphology_id)
                break
            else:
                log.debug('Waiting for morphology %d\'s script to generate: %s' % (
                    morphology_id, self.human_readable_seconds(seconds_elapsed)))
            sleep(wait)
            seconds_elapsed = seconds_elapsed + wait

        ################################################################################
        # MORPHEME LANGUAGE MODEL
        ################################################################################

        # Create a morpheme language model
        name = u'Blackfoot morpheme language model'
        params = self.morpheme_language_model_create_params.copy()
        params.update({
            'name': name,
            'corpus': rules_corpus_id,
            'toolkit': 'mitlm'
        })
        params = json.dumps(params)
        response = self.app.post(url('morphemelanguagemodels'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morpheme_language_model_id = resp['id']
        assert resp['name'] == name
        assert resp['toolkit'] == u'mitlm'
        assert resp['order'] == 3
        assert resp['smoothing'] == u'' # The ModKN smoothing algorithm is the implicit default with MITLM

        # Generate the files of the language model
        response = self.app.put(url(controller='morphemelanguagemodels', action='generate', id=morpheme_language_model_id),
            {}, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        lm_generate_attempt = resp['generate_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphemelanguagemodel', id=morpheme_language_model_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', lm_generate_attempt, log, wait=1, vocal=False)
        assert resp['generate_message'] == u'Language model successfully generated.'

        ################################################################################
        # MORPHOLOGICAL PARSER
        ################################################################################

        # Create a morphological parser for Blackfoot
        params = self.morphological_parser_create_params.copy()
        params.update({
            'name': u'Morphological parser for Blackfoot',
            'phonology': phonology_id,
            'morphology': morphology_id,
            'language_model': morpheme_language_model_id
        })
        params = json.dumps(params)
        response = self.app.post(url('morphologicalparsers'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_id = resp['id']

        # Compile the morphological parser's morphophonology script if necessary, cf. precompiled_morphophonology and pregenerated_morphophonology.
        morphological_parser_directory = os.path.join(self.morphological_parsers_path, 'morphological_parser_%d' % morphological_parser_id)
        morphophonology_binary_filename = 'morphophonology_%d.foma' % morphological_parser_id
        morphophonology_script_filename = 'morphological_parser_%d.script' % morphological_parser_id
        morphophonology_binary_path = os.path.join(morphological_parser_directory, morphophonology_binary_filename )
        morphophonology_script_path = os.path.join(morphological_parser_directory, morphophonology_script_filename )
        try:
            precompiled_morphophonology_path = os.path.join(self.test_morphophonologies_path, precompiled_morphophonology)
            pregenerated_morphophonology_path = os.path.join(self.test_morphophonologies_path, pregenerated_morphophonology)
        except Exception:
            precompiled_morphophonology_path = None
            pregenerated_morphophonology_path = None
        if (precompiled_morphophonology_path and pregenerated_morphophonology_path and 
           os.path.exists(precompiled_morphophonology_path) and os.path.exists(pregenerated_morphophonology_path)):
            # Use the precompiled morphophonology script if it's available,
            copyfileobj(open(precompiled_morphophonology_path, 'rb'), open(morphophonology_binary_path, 'wb'))
            copyfileobj(open(pregenerated_morphophonology_path, 'rb'), open(morphophonology_script_path, 'wb'))
        else:
            # Generate the parser's morphophonology FST, compile it and generate the morphemic language model
            response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
                id=morphological_parser_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
            resp = json.loads(response.body)
            morphological_parser_compile_attempt = resp['compile_attempt']

            # Poll ``GET /morphologicalparsers/morphological_parser_id`` until ``compile_attempt`` has changed.
            seconds_elapsed = 0
            wait = 10
            while True:
                response = self.app.get(url('morphologicalparser', id=morphological_parser_id),
                            headers=self.json_headers, extra_environ=self.extra_environ_contrib)
                resp = json.loads(response.body)
                if morphological_parser_compile_attempt != resp['compile_attempt']:
                    log.debug('Compile attempt for morphological parser %d has terminated.' % morphological_parser_id)
                    break
                else:
                    log.debug('Waiting for morphological parser %d to compile (%s) ...' % (
                        morphological_parser_id, self.human_readable_seconds(seconds_elapsed)))
                sleep(wait)
                seconds_elapsed = seconds_elapsed + wait

        # Test applyup on the mophological parser's morphophonology FST
        transcription1 = u'nitsspiyi'
        transcription1_correct_parse = u'nit%s1-ihpiyi%sdance' % (h.rare_delimiter, h.rare_delimiter)
        transcription2 = u'aaniit'
        transcription2_correct_parse = u'waanii%ssay-t%sIMP' % (h.rare_delimiter, h.rare_delimiter)
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_correct_parse in resp[transcription1]
        #log.debug('These are the parses for %s:' % transcription1)
        #log.debug(u'\n'.join(pretty_parses(resp[transcription1])))
        assert transcription2_correct_parse in resp[transcription2]
        #log.debug('These are the parses for %s:' % transcription2)
        #log.debug(u'\n'.join(pretty_parses(resp[transcription2])))

        # Test how well the morphological parser parses some test words.
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_correct_parse
        # aaniit will have waaniit 'scatter' as its most likely parse and the correct parse waanii-t 'say-IMP'
        # as its second most likely...
        assert resp[transcription2] != transcription2_correct_parse

        # Finally, load the original database back in so that subsequent tests can work.
        with open(tmp_script_path, 'w') as tmpscript:
            tmpscript.write('#!/bin/sh\nmysql -u %s -p%s %s < %s' % (username, password, db_name, backup_dump_file_path))
        with open(os.devnull, "w") as fnull:
            call([tmp_script_path], stdout=fnull, stderr=fnull)
        os.remove(tmp_script_path)
        os.remove(backup_dump_file_path)

        # Write tests for index, show, new/edit, update and history
        # The morpho parser as currently implemented encodes only a small subset of Bf morphology -- enlarge it!
        # Implement category-based class LMs and test them against morpheme-based ones.
        # Build multiple Bf morphological parsers and test them out, find the best one, write a paper on it!

    #@nottest
    def test_z_cleanup(self):
        """Clean up after the tests."""

        TestController.tearDown(
                self,
                clear_all_tables=True,
                del_global_app_set=True,
                dirs_to_destroy=['user', 'morphology', 'corpus', 'morphological_parser'])

