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

import hashlib
import logging
import os
import codecs
from shutil import copyfileobj
import simplejson as json
from time import sleep
from nose.tools import nottest
from onlinelinguisticdatabase.tests import TestController, url
import onlinelinguisticdatabase.model as model
from onlinelinguisticdatabase.model.meta import Session
from subprocess import call
import onlinelinguisticdatabase.lib.helpers as h
from onlinelinguisticdatabase.model import MorphologicalParser, MorphologicalParserBackup
from sqlalchemy.sql import desc

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
    def test_a_general(self):
        """General purpose test for morphological parsers.

        This is a lengthy, linear test.  Here is an overview:

        1. create application settings
        2. create forms
        3. create 2 morphologies, one with impoverished morpheme representations
        4. create a phonology
        5. create 2 language models, one categorial
        6. create 4 parsers -- all combinations of +-impoverished and +-categorial

        TODO: test servecompiled

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
            'Agr': model.SyntacticCategory(name=u'Agr'),
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
            ('ait', 'ait', '3IMP', 'third person imparfait', cats['Agr']),
            ('aient', 'aient', '3PL.IMPV', 'third person plural imperfective', cats['AGR']),

            ('Les chats nageaient.', 'le-s chat-s nage-aient', 'the-PL cat-PL swim-3PL.IMPV',
                'The cats were swimming.', cats['S']),
            ('La tortue parlait', 'la tortue parle-ait', 'the turtle speak-3SG.IMPV',
                'The turtle was speaking.', cats['S']),
            ('La tortue tombait', 'la tortue tombe-ait', 'the turtle fall-3SG.IMPV',
                'The turtle was falling.', cats['S']),
            ('Le chien parlait', 'le chien parle-ait', 'the dog speak-3IMP',
                'The dog was speaking.', cats['S'])
        )

        for tuple_ in dataset:
            self.create_form(*map(unicode, tuple_))

        # Create a form search model that returns lexical items (will be used to create the lexicon corpus)
        query = {'filter': ['Form', 'syntactic_category', 'name', 'in', [u'N', u'V', u'AGR', u'PHI', u'D', u'Agr']]}
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
        morphology_params = self.morphology_create_params.copy()
        morphology_params.update({
            'name': name,
            'lexicon_corpus': lexicon_corpus_id,
            'rules_corpus': rules_corpus_id,
            'script_type': 'regex'
        })
        morphology_params = json.dumps(morphology_params)
        response = self.app.post(url('morphologies'), morphology_params,
                self.json_headers, self.extra_environ_admin)
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
        requester = lambda: self.app.get(url('morphology', id=morphology_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', compile_attempt, log, wait=1,
            vocal=True, task_descr='compile morphology %s' % morphology_id)
        assert resp['compile_message'] == \
            u'Compilation process terminated successfully and new binary file was written.'

        response = self.app.get(url('morphology', id=morphology_id), params={'script': u'1', 'lexicon': u'1'},
                    headers=self.json_headers, extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        morphology_dir = os.path.join(self.morphologies_path, 'morphology_%d' % morphology_id)
        morphology_binary_filename = 'morphology.foma'
        morphology_dir_contents = os.listdir(morphology_dir)
        morphology_script_path = os.path.join(morphology_dir, 'morphology.script')
        morphology_script = codecs.open(morphology_script_path, mode='r', encoding='utf8').read()
        assert u'define morphology' in morphology_script
        assert u'(NCat)' in morphology_script # cf. tortue
        assert u'(DCat)' in morphology_script # cf. la
        assert u'(NCat "-" PHICat)' in morphology_script # cf. chien-s
        assert u'(DCat "-" PHICat)' in morphology_script # cf. le-s
        assert u'(VCat "-" AGRCat)' in morphology_script # cf. nage-aient, parle-ait
        assert u'c h a t "%scat%sN":0' % (h.rare_delimiter, h.rare_delimiter) in morphology_script # cf. extract_morphemes_from_rules_corpus = False and chat's exclusion from the lexicon corpus
        assert u'c h i e n "%sdog%sN":0' % (h.rare_delimiter, h.rare_delimiter) in morphology_script
        assert u'b e \u0301 c a s s e "%swoodcock%sN":0' % (h.rare_delimiter, h.rare_delimiter) in morphology_script
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

        ################################################################################
        # BEGIN IMPOVERISHED REPRESENTATION MORPHOLOGY
        ################################################################################

        # Create a new morphology, this time one that parses to impoverished representations.
        impoverished_name = u'Morphology of a very small subset of french, impoverished morphemes'
        morphology_params = self.morphology_create_params.copy()
        morphology_params.update({
            'name': impoverished_name,
            'lexicon_corpus': lexicon_corpus_id,
            'rules_corpus': rules_corpus_id,
            'script_type': 'regex',
            'rich_morphemes': False
        })
        morphology_params = json.dumps(morphology_params)
        response = self.app.post(url('morphologies'), morphology_params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        impoverished_morphology_id = resp['id']
        assert resp['name'] == impoverished_name
        assert resp['script_type'] == u'regex'

        # Compile the morphology's script
        response = self.app.put(url(controller='morphologies', action='generate_and_compile',
                    id=impoverished_morphology_id), headers=self.json_headers,
                    extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        compile_attempt = resp['compile_attempt']

        # Poll ``GET /morphologies/morphology_id`` until ``compile_attempt`` has changed.
        requester = lambda: self.app.get(url('morphology', id=impoverished_morphology_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', compile_attempt, log, wait=1,
            vocal=True, task_descr='compile morphology %s' % impoverished_morphology_id)
        assert resp['compile_message'] == \
            u'Compilation process terminated successfully and new binary file was written.'

        response = self.app.get(url('morphology', id=impoverished_morphology_id), params={'script': u'1', 'lexicon': u'1'},
                    headers=self.json_headers, extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        morphology_dir = os.path.join(self.morphologies_path, 'morphology_%d' % impoverished_morphology_id)
        morphology_binary_filename = 'morphology.foma'
        morphology_dir_contents = os.listdir(morphology_dir)
        morphology_script_path = os.path.join(morphology_dir, 'morphology.script')
        morphology_script = codecs.open(morphology_script_path, mode='r', encoding='utf8').read()
        assert u'define morphology' in morphology_script
        assert u'(NCat)' in morphology_script # cf. tortue
        assert u'(DCat)' in morphology_script # cf. la
        assert u'(NCat "-" PHICat)' in morphology_script # cf. chien-s
        assert u'(DCat "-" PHICat)' in morphology_script # cf. le-s
        assert u'(VCat "-" AGRCat)' in morphology_script # cf. nage-aient, parle-ait
        assert u'c h a t' in morphology_script # cf. extract_morphemes_from_rules_corpus = False and chat's exclusion from the lexicon corpus
        assert u'c h i e n' in morphology_script
        assert u'b e \u0301 c a s s e' in morphology_script
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
        response = self.app.get(url('morphology', id=impoverished_morphology_id), params={'script': u'1', 'lexicon': u'1'},
                    headers=self.json_headers, extra_environ=self.extra_environ_contrib)
        resp = json.loads(response.body)
        assert resp['script'] == morphology_script
        lexicon = resp['lexicon']
        assert ['s', 'PL'] in lexicon['PHI']
        assert ['oiseau', 'bird'] in lexicon['N']
        assert ['aient', '3PL.IMPV'] in lexicon['AGR']
        assert ['la', 'the'] in lexicon['D']
        assert ['nage', 'swim'] in lexicon['V']

        ################################################################################
        # END IMPOVERISHED REPRESENTATION MORPHOLOGY
        ################################################################################

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

        ################################################################################
        # LANGUAGE MODEL 1 
        ################################################################################

        # Create a corpus heavily stacked towards tombe|fall-ait|3SG.IMPV and V-AGR
        # as opposed to tombe|fall-ait|3IMP and V-Agr.
        sentences = Session.query(model.Form).filter(model.Form.syntactic_category.has(
            model.SyntacticCategory.name==u'S')).all()
        target_id = [s for s in sentences if s.transcription == u'La tortue tombait'][0].id
        sentence_ids = [s.id for s in sentences] + [target_id] * 100
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of sentences with lots of form %s' % target_id,
            'content': u','.join(map(unicode, sentence_ids))
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        lm_corpus_id = json.loads(response.body)['id']

        # Create the LM using lm_corpus
        name = u'Morpheme language model'
        params = self.morpheme_language_model_create_params.copy()
        params.update({
            'name': name,
            'corpus': lm_corpus_id,
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
        # LANGUAGE MODEL 2 -- CATEGORIAL
        ################################################################################

        categorial_lm_name = u'Morpheme language model -- categorial'
        params = self.morpheme_language_model_create_params.copy()
        params.update({
            'name': categorial_lm_name,
            'corpus': lm_corpus_id,
            'toolkit': 'mitlm',
            'categorial': True
        })
        params = json.dumps(params)
        response = self.app.post(url('morphemelanguagemodels'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        categorial_language_model_id = resp['id']
        assert resp['name'] == categorial_lm_name
        assert resp['toolkit'] == u'mitlm'
        assert resp['order'] == 3
        assert resp['smoothing'] == u'' # The ModKN smoothing algorithm is the implicit default with MITLM
        assert resp['categorial'] == True

        # Generate the files of the language model
        response = self.app.put(url(controller='morphemelanguagemodels', action='generate',
            id=categorial_language_model_id),
            {}, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        lm_generate_attempt = resp['generate_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphemelanguagemodel', id=categorial_language_model_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', lm_generate_attempt, log, wait=1, vocal=False)
        assert resp['generate_message'] == u'Language model successfully generated.'

        ################################################################################
        # TRANSCRIPTIONS & PARSES
        ################################################################################

        transcription1 = u'tombait'
        transcription1_correct_parse = u'%s-%s' % (
                h.rare_delimiter.join([u'tombe', u'fall', u'V']),
                h.rare_delimiter.join([u'ait', u'3SG.IMPV', u'AGR']))
        transcription1_alt_parse = u'%s-%s' % (
                h.rare_delimiter.join([u'tombe', u'fall', u'V']),
                h.rare_delimiter.join([u'ait', u'3IMP', u'Agr']))
        transcription1_impoverished_parse = u'tombe-ait'
        transcription2 = u'tombeait'
        transcription3 = u'chiens'
        transcription3_correct_parse = u'%s-%s' % (
                h.rare_delimiter.join([u'chien', u'dog', u'N']),
                h.rare_delimiter.join([u's', u'PL', u'PHI']))
        transcription3_impoverished_parse = u'chiens-s'


        ################################################################################
        # MORPHOLOGICAL PARSER 1
        ################################################################################

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
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_correct_parse in resp[transcription1]
        assert len(resp[transcription1]) == 2
        assert resp[transcription2] == []

        # Test how well the morphological parser parses some test words.
        # In-memory cache will result in the second request to parse transcription 1
        # being accomplished via dict lookup.  Parses for both transcriptions 1 and 2
        # will be persisted across requests in the ``parse`` table.
        params = json.dumps({'transcriptions': [transcription1, transcription1, transcription3]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_correct_parse
        assert resp[transcription3] == transcription3_correct_parse

        # Make the same parse request again.  This time the persistent cache will be used
        # and all of the parses returned will be from the cache, i.e., no subprocesses to 
        # flookup will be initiated.
        params = json.dumps({'transcriptions': [transcription1, transcription1, transcription3, 'abc']})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_correct_parse
        assert resp[transcription3] == transcription3_correct_parse
        assert resp['abc'] == None

        ################################################################################
        # END MORPHOLOGICAL PARSER 1
        ################################################################################

        ################################################################################
        # MORPHOLOGICAL PARSER 2
        ################################################################################

        # Create an impoverished morphemes morphological parser for toy french
        params = self.morphological_parser_create_params.copy()
        params.update({
            'name': u'Morphological parser for toy French, impoverished morphemes',
            'phonology': phonology_id,
            'morphology': impoverished_morphology_id,
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
        # Because the morphology returns impoverished representations, the morphophonology_
        # will too.
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_impoverished_parse in resp[transcription1]
        assert len(resp[transcription1]) == 1
        assert resp[transcription2] == []

        # Test applydown on the mophological parser's morphophonology FST
        params = json.dumps({'morpheme_sequences': [transcription1_impoverished_parse]})
        response = self.app.put(url(controller='morphologicalparsers', action='applydown',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1 in resp[transcription1_impoverished_parse]

        # Test how well the morphological parser parses some test words.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)

        # Note how the rich representation is always returned by a parser even if its morphophonology
        # returns impoverished ones.  The ``parse`` action disambiguates the morphemic analysis received
        # from the morphophonology before selecting the most probable candidate.
        assert resp[transcription1] == transcription1_correct_parse

        ################################################################################
        # END MORPHOLOGICAL PARSER 2
        ################################################################################

        ################################################################################
        # MORPHOLOGICAL PARSER 3 -- categorial LM
        ################################################################################

        # Create categorial LM  morphological parser for toy french
        params = self.morphological_parser_create_params.copy()
        params.update({
            'name': u'Morphological parser for toy French, categorial LM',
            'phonology': phonology_id,
            'morphology': morphology_id,
            'language_model': categorial_language_model_id
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

        # Test applyup on the mophological parser's morphophonology FST.  Everything should
        # work just like parser #1.
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_correct_parse in resp[transcription1]
        assert len(resp[transcription1]) == 2
        assert resp[transcription2] == []

        # Test applydown on the mophological parser's morphophonology FST
        params = json.dumps({'morpheme_sequences': [transcription1_correct_parse]})
        response = self.app.put(url(controller='morphologicalparsers', action='applydown',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1 in resp[transcription1_correct_parse]

        # Test how well the morphological parser parses some test words.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        # There is only one possible parse for transcription 1 -- it is de facto the most probable
        assert resp[transcription1] == transcription1_correct_parse

        ################################################################################
        # END MORPHOLOGICAL PARSER 3
        ################################################################################

        ################################################################################
        # MORPHOLOGICAL PARSER 4 -- categorial LM & impoverished morphology
        ################################################################################

        # Create categorial LM, impoverished morphology morphological parser for toy french
        params = self.morphological_parser_create_params.copy()
        params.update({
            'name': u'Morphological parser for toy French, categorial LM, impoverished morphology',
            'phonology': phonology_id,
            'morphology': impoverished_morphology_id,
            'language_model': categorial_language_model_id
        })
        params = json.dumps(params)
        response = self.app.post(url('morphologicalparsers'), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_id = parser_4_id = resp['id']

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

        # Test applyup on the mophological parser's morphophonology FST.  Expect to get morpheme 
        # form sequences. 
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1_impoverished_parse in resp[transcription1]
        assert len(resp[transcription1]) == 1
        assert resp[transcription2] == []

        # Test applydown on the mophological parser's morphophonology FST
        params = json.dumps({'morpheme_sequences': [transcription1_impoverished_parse]})
        response = self.app.put(url(controller='morphologicalparsers', action='applydown',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert transcription1 in resp[transcription1_impoverished_parse]

        # Test how well the morphological parser parses some test words.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        # parse time disambiguation and categorial LM application should all conspire to return the correct parse...
        assert resp[transcription1] == transcription1_correct_parse

        ################################################################################
        # END MORPHOLOGICAL PARSER 4
        ################################################################################

        ################################################################################
        # TEST PARSER DEPENDENCY REPLICATION
        ################################################################################

        # Vacuously re-generate and re-compile the parser
        ################################################################################

        # Show that the cache will not be cleared.

        parser_4_parses = sorted([parse.transcription for parse in Session.query(model.Parse).\
            filter(model.Parse.parser_id==parser_4_id).all()])

        response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
            id=parser_4_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_compile_attempt = resp['compile_attempt']

        # Poll GET /morphologicalparsers/id until compile_attempt changes.
        requester = lambda: self.app.get(url('morphologicalparser', id=parser_4_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'compile_attempt', morphological_parser_compile_attempt,
            log, wait=1, vocal=True, task_descr='compile parser %s' % parser_4_id)

        # Perform the same parse request as previously and expect the same results.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=parser_4_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_correct_parse

        parser_4_parses_now = sorted([parse.transcription for parse in Session.query(model.Parse).\
            filter(model.Parse.parser_id==parser_4_id).all()])
        assert parser_4_parses == parser_4_parses_now

        # Update the parser's LM
        ################################################################################

        # The parsing behaviour of the parser will not change because it has not been
        # re-generated or re-compiled.

        # For the updated LM, create a new corpus heavily stacked towards V-Agr.
        sentences = Session.query(model.Form).filter(model.Form.syntactic_category.has(
            model.SyntacticCategory.name==u'S')).all()
        # The sentence below is analyzed using an Agr-categorized suffix
        target_id = [s for s in sentences if s.transcription == u'Le chien parlait'][0].id
        sentence_ids = [s.id for s in sentences] + [target_id] * 100
        params = self.corpus_create_params.copy()
        params.update({
            'name': u'Corpus of sentences with lots of form %s' % target_id,
            'content': u','.join(map(unicode, sentence_ids))
        })
        params = json.dumps(params)
        response = self.app.post(url('corpora'), params, self.json_headers, self.extra_environ_admin)
        lm_corpus_2_id = json.loads(response.body)['id']

        # update the categorial LM so that its corpus is the newly created one.
        params = self.morpheme_language_model_create_params.copy()
        params.update({
            'name': categorial_lm_name,
            'corpus': lm_corpus_2_id, # HERE IS THE CHANGE
            'toolkit': 'mitlm',
            'categorial': True
        })
        params = json.dumps(params)
        response = self.app.put(url('morphemelanguagemodel', id=categorial_language_model_id),
                params, self.json_headers, self.extra_environ_admin)

        # Request that the files of the language model be generated anew; this will create a new
        # LMTree pickle file.
        response = self.app.put(url(controller='morphemelanguagemodels', action='generate',
            id=categorial_language_model_id),
            {}, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        lm_generate_attempt = resp['generate_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphemelanguagemodel', id=categorial_language_model_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'generate_attempt', lm_generate_attempt, log, wait=1, vocal=False)
        assert resp['generate_message'] == u'Language model successfully generated.'

        # Now if we try to parse "tombait" using parser #4 we will still get the V-AGR parse
        # even though the LM associated to that parser (the categorial one) has been changed to be
        # weighted heavily towards the V-Agr parse.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=parser_4_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_correct_parse

        # Request probabilities form the just re-generated LM and expect V-Agr to be higher.
        likely_word = u'V Agr'
        unlikely_word = u'V AGR'
        ms_params = json.dumps({'morpheme_sequences': [likely_word, unlikely_word]})
        response = self.app.put(url(controller='morphemelanguagemodels', action='get_probabilities',
            id=categorial_language_model_id), ms_params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        likely_word_log_prob = resp[likely_word]
        unlikely_word_log_prob = resp[unlikely_word]
        assert likely_word_log_prob > unlikely_word_log_prob

        # Re-generate and re-compile the parser
        ################################################################################

        # Expect it to now parse tombait as tombe-ait fall-3IMP V-Agr

        response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
            id=parser_4_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_compile_attempt = resp['compile_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphologicalparser', id=parser_4_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'compile_attempt', morphological_parser_compile_attempt,
            log, wait=1, vocal=True, task_descr='compile parser %s' % parser_4_id)

        # Perform the same parse request as above and expect different results.
        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=parser_4_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] != transcription1_correct_parse
        assert resp[transcription1] == transcription1_alt_parse

        # Delete the parser's LM
        ################################################################################

        # Expect it to still work as previously.

        response = self.app.delete(url('morphemelanguagemodel', id=categorial_language_model_id),
                                   headers=self.json_headers, extra_environ=self.extra_environ_admin)

        params = json.dumps({'transcriptions': [transcription1]})
        response = self.app.put(url(controller='morphologicalparsers', action='parse',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp[transcription1] == transcription1_alt_parse

        # If we re-generate and re-compile, the compile will succeed (since it requires only a 
        # phonology and a morphology) while the generate attempt will fail because there 
        # will be no LM object to copy attribute values and file objects from.
        response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
            id=parser_4_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        morphological_parser_compile_attempt = resp['compile_attempt']

        # Poll GET /morphemelanguagemodels/id until generate_attempt changes.
        requester = lambda: self.app.get(url('morphologicalparser', id=parser_4_id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = self.poll(requester, 'compile_attempt', morphological_parser_compile_attempt,
            log, wait=1, vocal=True, task_descr='compile parser %s' % parser_4_id)
        assert resp['compile_succeeded'] == True
        assert resp['generate_succeeded'] == False

        # Test GET /morphologicalparsers
        ################################################################################

        morphological_parsers = Session.query(MorphologicalParser).all()

        # Get all morphological parsers
        response = self.app.get(url('morphologicalparsers'), headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert len(resp) == 4

        # Test the paginator GET params.
        paginator = {'items_per_page': 1, 'page': 1}
        response = self.app.get(url('morphologicalparsers'), paginator, headers=self.json_headers,
                                extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert len(resp['items']) == 1
        assert resp['items'][0]['name'] == morphological_parsers[0].name
        assert response.content_type == 'application/json'

        # Test the order_by GET params.
        order_by_params = {'order_by_model': 'MorphologicalParser', 'order_by_attribute': 'id',
                     'order_by_direction': 'desc'}
        response = self.app.get(url('morphologicalparsers'), order_by_params,
                        headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert resp[0]['id'] == morphological_parsers[-1].id
        assert response.content_type == 'application/json'

        # Test the order_by *with* paginator.
        params = {'order_by_model': 'MorphologicalParser', 'order_by_attribute': 'id',
                     'order_by_direction': 'desc', 'items_per_page': 1, 'page': 4}
        response = self.app.get(url('morphologicalparsers'), params,
                        headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert morphological_parsers[0].name == resp['items'][0]['name']

        # Expect a 400 error when the order_by_direction param is invalid
        order_by_params = {'order_by_model': 'MorphologicalParser', 'order_by_attribute': 'name',
                     'order_by_direction': 'descending'}
        response = self.app.get(url('morphologicalparsers'), order_by_params, status=400,
            headers=self.json_headers, extra_environ=self.extra_environ_view)
        resp = json.loads(response.body)
        assert resp['errors']['order_by_direction'] == u"Value must be one of: asc; desc (not u'descending')"
        assert response.content_type == 'application/json'

        # Test that GET /morphologicalparsers/<id> works correctly.

        # Try to get a morphological parser using an invalid id
        id = 100000000000
        response = self.app.get(url('morphologicalparser', id=id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin, status=404)
        resp = json.loads(response.body)
        assert u'There is no morphological parser with id %s' % id in json.loads(response.body)['error']
        assert response.content_type == 'application/json'

        # No id
        response = self.app.get(url('morphologicalparser', id=''), status=404,
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert json.loads(response.body)['error'] == 'The resource could not be found.'
        assert response.content_type == 'application/json'

        # Valid id
        response = self.app.get(url('morphologicalparser', id=morphological_parsers[0].id), headers=self.json_headers,
                                extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp['name'] == morphological_parsers[0].name
        assert resp['description'] == morphological_parsers[0].description
        assert response.content_type == 'application/json'

        # Tests that GET /morphologicalparsers/new and GET /morphologicalparsers/id/edit return 
        # the data needed to create or update a morphological parser.

        # Test GET /morphologicalparsers/new
        response = self.app.get(url('new_morphologicalparser'), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert len(resp['phonologies']) == 1
        assert len(resp['morphologies']) == 2
        assert len(resp['morpheme_language_models']) == 1

        # Not logged in: expect 401 Unauthorized
        response = self.app.get(url('edit_morphologicalparser', id=morphological_parsers[0].id), status=401)
        resp = json.loads(response.body)
        assert resp['error'] == u'Authentication is required to access this resource.'
        assert response.content_type == 'application/json'

        # Invalid id
        id = 9876544
        response = self.app.get(url('edit_morphologicalparser', id=id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin,
            status=404)
        assert u'There is no morphological parser with id %s' % id in json.loads(response.body)['error']
        assert response.content_type == 'application/json'

        # No id
        response = self.app.get(url('edit_morphologicalparser', id=''), status=404,
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert json.loads(response.body)['error'] == 'The resource could not be found.'
        assert response.content_type == 'application/json'

        # Valid id
        response = self.app.get(url('edit_morphologicalparser', id=morphological_parsers[0].id),
            headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert resp['morphological_parser']['name'] == morphological_parsers[0].name
        assert len(resp['data']['phonologies']) == 1
        assert len(resp['data']['morphologies']) == 2
        assert len(resp['data']['morpheme_language_models']) == 1
        assert response.content_type == 'application/json'

        # Tests that PUT /morphologicalparsers/id updates the morphological parser with id=id.

        foma_installed = h.foma_installed(force_check=True)

        morphological_parsers = [json.loads(json.dumps(m, cls=h.JSONOLDEncoder))
            for m in Session.query(MorphologicalParser).all()]
        morphological_parser_1_id = morphological_parsers[0]['id']
        morphological_parser_1_name = morphological_parsers[0]['name']
        morphological_parser_1_description = morphological_parsers[0]['description']
        morphological_parser_1_modified = morphological_parsers[0]['datetime_modified']
        morphological_parser_1_phonology_id = morphological_parsers[0]['phonology']['id']
        morphological_parser_1_morphology_id = morphological_parsers[0]['morphology']['id']
        morphological_parser_1_lm_id = morphological_parsers[0]['language_model']['id']
        morphological_parser_count = len(morphological_parsers)
        morphological_parser_1_dir = os.path.join(self.morphological_parsers_path,
                'morphological_parser_%d' % morphological_parser_1_id)
        morphological_parser_1_morphophonology_path = os.path.join(
                morphological_parser_1_dir, 'morphophonology.script')
        if foma_installed:
            morphology_1_morphophonology = codecs.open(morphological_parser_1_morphophonology_path,
                    mode='r', encoding='utf8').read()

        # Update the first morphological parser.
        original_backup_count = Session.query(MorphologicalParserBackup).count()
        params = self.morphology_create_params.copy()
        params.update({
            'name': morphological_parser_1_name,
            'description': u'New description',
            'phonology': morphological_parser_1_phonology_id,
            'morphology': morphological_parser_1_morphology_id,
            'language_model': morphological_parser_1_lm_id
        })
        params = json.dumps(params)
        response = self.app.put(url('morphologicalparser', id=morphological_parser_1_id), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        new_backup_count = Session.query(MorphologicalParserBackup).count()
        datetime_modified = resp['datetime_modified']
        new_morphological_parser_count = Session.query(MorphologicalParser).count()
        assert morphological_parser_count == new_morphological_parser_count
        assert datetime_modified != morphological_parser_1_modified
        assert resp['description'] == u'New description'
        assert response.content_type == 'application/json'
        assert original_backup_count + 1 == new_backup_count
        backup = Session.query(MorphologicalParserBackup).filter(
            MorphologicalParserBackup.UUID==unicode(
            resp['UUID'])).order_by(
            desc(MorphologicalParserBackup.id)).first()
        assert backup.datetime_modified.isoformat() == morphological_parser_1_modified
        assert backup.description == morphological_parser_1_description
        assert response.content_type == 'application/json'

        # Attempt an update with no new input and expect to fail
        response = self.app.put(url('morphologicalparser', id=morphological_parser_1_id), params, self.json_headers,
                                 self.extra_environ_admin, status=400)
        resp = json.loads(response.body)
        morphological_parser_count = new_morphological_parser_count
        new_morphological_parser_count = Session.query(MorphologicalParser).count()
        our_morphological_parser_datetime_modified = Session.query(
                MorphologicalParser).get(morphological_parser_1_id).datetime_modified
        assert our_morphological_parser_datetime_modified.isoformat() == datetime_modified
        assert morphological_parser_count == new_morphological_parser_count
        assert resp['error'] == u'The update request failed because the submitted data were not new.'
        assert response.content_type == 'application/json'

        # Update the first morphological parser again.
        original_backup_count = new_backup_count
        params = self.morphology_create_params.copy()
        params.update({
            'name': morphological_parser_1_name,
            'description': u'Newer description',
            'phonology': morphological_parser_1_phonology_id,
            'morphology': morphological_parser_1_morphology_id,
            'language_model': morphological_parser_1_lm_id
        })
        params = json.dumps(params)
        response = self.app.put(url('morphologicalparser', id=morphological_parser_1_id), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        new_backup_count = Session.query(MorphologicalParserBackup).count()
        datetime_modified = resp['datetime_modified']
        morphological_parser_count = new_morphological_parser_count
        new_morphological_parser_count = Session.query(MorphologicalParser).count()
        assert morphological_parser_count == new_morphological_parser_count
        assert resp['description'] == u'Newer description'
        assert response.content_type == 'application/json'
        assert original_backup_count + 1 == new_backup_count
        backup = Session.query(MorphologicalParserBackup).filter(
            MorphologicalParserBackup.UUID==unicode(
            resp['UUID'])).order_by(
            desc(MorphologicalParserBackup.id)).first()
        assert backup.datetime_modified.isoformat() == our_morphological_parser_datetime_modified.isoformat()
        assert backup.description == u'New description'
        assert response.content_type == 'application/json'

        # Tests that GET /morphologicalparsers//id/history returns the morphological parser with id=id and its previous incarnations.

        morphological_parser_1_backup_count = Session.query(MorphologicalParserBackup).count() # there should only be backups of parser #1
        morphological_parsers = Session.query(MorphologicalParser).all()
        morphological_parser_1_id = morphological_parsers[0].id
        morphological_parser_1_UUID = morphological_parsers[0].UUID

        # Now get the history of the first morphological parser (which was updated twice in ``test_update``.
        response = self.app.get(
            url(controller='morphologicalparsers', action='history', id=morphological_parser_1_id),
            headers=self.json_headers, extra_environ=self.extra_environ_view_appset)
        resp = json.loads(response.body)
        assert response.content_type == 'application/json'
        assert 'morphological_parser' in resp
        assert 'previous_versions' in resp
        assert len(resp['previous_versions']) == morphological_parser_1_backup_count

        # Get the same history as above, except use the UUID
        response = self.app.get(
            url(controller='morphologicalparsers', action='history', id=morphological_parser_1_UUID),
            headers=self.json_headers, extra_environ=self.extra_environ_view_appset)
        resp = json.loads(response.body)
        assert response.content_type == 'application/json'
        assert 'morphological_parser' in resp
        assert 'previous_versions' in resp
        assert len(resp['previous_versions']) == morphological_parser_1_backup_count

        # Attempt to get the history with an invalid id and expect to fail
        response = self.app.get(
            url(controller='morphologicalparsers', action='history', id=123456789),
            headers=self.json_headers, extra_environ=self.extra_environ_view_appset, status=404)
        resp = json.loads(response.body)
        assert response.content_type == 'application/json'
        assert resp['error'] == u'No morphological parsers or morphological parser backups match 123456789'

        # Test servecompiled
        response = self.app.get(url(controller='morphologicalparsers', action='servecompiled',
            id=morphological_parser_1_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        binary_path = os.path.join(morphological_parser_1_dir, 'morphophonology.foma')
        binary_file = open(binary_path, 'rb').read()
        binary_file_from_resp = response.body
        assert binary_file == binary_file_from_resp

        # Test export
        response = self.app.get(url(controller='morphologicalparsers', action='export',
            id=morphological_parser_1_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)
        assert response.content_type == 'application/zip'
        # To ensure the exported parser works, unzip it and test it out: ./parse.py chiens chats

        parser_1_cache = sorted([p.transcription for p in Session.query(model.Parse).\
            filter(model.Parse.parser_id==morphological_parser_1_id).all()])
        assert parser_1_cache == [u'abc', u'chiens', u'tombait']

        # Test morphological parser deletion.
        assert u'morphophonology.script' in os.listdir(morphological_parser_1_dir)
        assert u'morphophonology.foma' in os.listdir(morphological_parser_1_dir)
        response = self.app.delete(url('morphologicalparser', id=morphological_parser_1_id),
                                   headers=self.json_headers, extra_environ=self.extra_environ_admin)
        resp = json.loads(response.body)
        assert not os.path.exists(morphological_parser_1_dir)
        assert resp['description'] == u'Newer description'
        assert resp['phonology']['id'] == morphological_parser_1_phonology_id

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
        pregenerated_morphophonology = None # 'blaold_morphophonology.script'
        precompiled_morphophonology = None # 'blaold_morphophonology.foma'

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
        rich_morphemes = False
        name = u'Morphology of Blackfoot'
        params = self.morphology_create_params.copy()
        params.update({
            'name': name,
            'lexicon_corpus': lexicon_corpus_id,
            'rules': word_category_sequences,
            'script_type': u'lexc',
            'extract_morphemes_from_rules_corpus': False,
            'rich_morphemes': rich_morphemes
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
        morphophonology_binary_filename = 'morphophonology.foma'
        morphophonology_script_filename = 'morphological_parser.script'
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

            # Generate the parser's morphophonology FST, compile it and generate the morphemic language model
            response = self.app.put(url(controller='morphologicalparsers', action='generate_and_compile',
                id=morphological_parser_id), headers=self.json_headers, extra_environ=self.extra_environ_admin)

            # Poll ``GET /morphologicalparsers/mophological_parser_id`` until ``compile_attempt`` has changed.
            requester = lambda: self.app.get(url('morphologicalparser', id=morphological_parser_id),
                headers=self.json_headers, extra_environ=self.extra_environ_admin)
            resp = self.poll(requester, 'compile_attempt', morphological_parser_compile_attempt, log,
                    wait=10, vocal=True, task_descr='compile morphological parser %s' % morphological_parser_id)
            assert resp['compile_message'] == \
                u'Compilation process terminated successfully and new binary file was written.'

            # Poll ``GET /morphologicalparsers/mophological_parser_id`` until ``compile_attempt`` has changed.
            requester = lambda: self.app.get(url('morphologicalparser', id=morphological_parser_id),
                headers=self.json_headers, extra_environ=self.extra_environ_admin)
            resp = self.poll(requester, 'compile_attempt', morphological_parser_compile_attempt, log,
                    wait=10, vocal=True, task_descr='compile morphological parser %s' % morphological_parser_id)
            assert resp['compile_message'] == \
                u'Compilation process terminated successfully and new binary file was written.'

        # Some reusable transcriptions and their parses
        transcription1 = u'nitsspiyi'
        transcription1_correct_parse = u'%s-%s' % (
                h.rare_delimiter.join([u'nit', u'1', u'agra']),
                h.rare_delimiter.join([u'ihpiyi', u'dance', u'vai']))
        transcription1_impoverished_parse = u'nit-ihpiyi'
        transcription2 = u'aaniit'
        transcription2_correct_parse = u'%s-%s' % (
                h.rare_delimiter.join([u'waanii', u'say', u'vai']),
                h.rare_delimiter.join([u't', u'IMP', u'agrb']))
        transcription2_impoverished_parse = u'waanii-t'

        # Test applyup on the mophological parser's morphophonology FST
        params = json.dumps({'transcriptions': [transcription1, transcription2]})
        log.warn('about to applyup parser %d on %s and %s' % (
            morphological_parser_id, transcription1, transcription2))
        response = self.app.put(url(controller='morphologicalparsers', action='applyup',
                    id=morphological_parser_id), params, self.json_headers, self.extra_environ_admin)
        resp = json.loads(response.body)
        if rich_morphemes:
            assert transcription1_correct_parse in resp[transcription1]
            assert transcription2_correct_parse in resp[transcription2]
        else:
            assert transcription1_impoverished_parse in resp[transcription1]
            assert transcription2_impoverished_parse in resp[transcription2]

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

        # Implement category-based class LMs and test them against morpheme-based ones.
        # Build multiple Bf morphological parsers and test them out, find the best one, write a paper on it!

    @nottest
    def test_z_cleanup(self):
        """Clean up after the tests."""

        TestController.tearDown(
                self,
                clear_all_tables=True,
                del_global_app_set=True,
                dirs_to_destroy=['user', 'morphology', 'corpus', 'morphological_parser'])

