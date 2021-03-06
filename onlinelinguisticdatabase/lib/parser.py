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

"""Morphological parser repurposable functionality.

This module contains the core classes required for morphological parser functionality.
These classes provide subprocess-mediated interfaces to the foma program for finite-state
transducer creation and interaction as well as to the MITLM program for language model
creation and interaction.  The classes are:

    - Command(object)                -- general-purpose functionality for interfacing to a command-line program
    - FomaFST(Command)               -- interface to foma
    - Phonology(FomaFST)             -- phonology-specific interface to foma
    - Morphology(FomaFST)            -- morphology-specific interface to foma
    - LanguageModel(Command)         -- interface to LM toolkits (only MITLM at present)
    - MorphologicalParser(FomaFST)   -- basically a morphophonology foma FST that has a LM object

The last four classes are used as superclasses for the relevant OLD (SQLAlchemy) model objects.
The model classes implement OLD-specific functionality that generates the scripts, compilers,
log files, corpus files, vocabulary files, etc. of the FSTs and LMs.  The functionality
implemented here should be reusable in OLD-external programs.

"""

import logging
import codecs
import os
from shutil import copyfile
import errno
import re
import cPickle
from shutil import rmtree
from uuid import uuid4
from subprocess import Popen, PIPE
from itertools import product
import threading
from signal import SIGKILL
import simplelm

log = logging.getLogger(__name__)


class Command(object):
    """Python subprocess interface to a command line program.

    Primary method is ``run`` which executes the input command ``cmd`` as a
    subprocess within a thread.  A ``timeout`` argument to :func:`run` causes
    the process running the input ``cmd`` to be terminated at the end of
    ``timeout`` seconds if it hasn't terminated on its own.

    Cf. http://stackoverflow.com/questions/1191374/subprocess-with-timeout

    """

    def __init__(self, parent_directory, **kwargs):
        self.parent_directory = parent_directory
        self.object_type = kwargs.pop('object_type', u'command')
        self.make_directory_safely(self.directory)
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

    @property
    def file_type2extension(self):
        return {'log': '.log'}

    @property
    def verification_string(self):
        return u'defined %s: ' % self.object_type

    tablename2object_type = {}

    @property
    def object_type(self):
        try:
            return self._object_type
        except AttributeError:
            if hasattr(self, '__tablename__'):
                self._object_type = self.tablename2object_type.get(
                    self.__tablename__, self.__tablename__)
                return self._object_type
            else:
                raise AttributeError("'%s' object has not attribute 'object_type'" %
                    self.__class__.__name__)

    @object_type.setter
    def object_type(self, value):
        """You can't set the object_type value of an SQLAlchemy model."""
        if hasattr(self, '__tablename__'):
            self._object_type = self.tablename2object_type.get(
                self.__tablename__, self.__tablename__)
        else:
            self._object_type = value

    @property
    def logpath(self):
        return self.get_file_path('log')

    def get_file_path(self, file_type=None):
        """Return the path to the instance's file of the given type.

        :param str file_type: descriptor of the type of file to return a path for.
        :returns: an absolute path to the file of the supplied type for the object given.

        """
        return os.path.join(self.directory,
            '%s%s' % (self.file_name, self.file_type2extension.get(file_type, '')))

    @property
    def directory(self):
        """Return the path to this instance's directory."""
        if getattr(self, 'id', None):
            return os.path.join(self.parent_directory, '%s_%d' % (
                self.directory_name, self.id))
        else:
            # This is the (assumedly) non-SQLA/OLD case: we create all files in parent_directory
            return self.parent_directory

    object_type2directory_name = {}
    object_type2file_name = {}

    @property
    def directory_name(self):
        object_type = self.object_type
        return self.object_type2directory_name.get(object_type, object_type)

    @property
    def file_name(self):
        object_type = self.object_type
        return self.object_type2file_name.get(object_type, object_type)

    def make_directory_safely(self, path):
        """Create a directory and avoid race conditions.
        http://stackoverflow.com/questions/273192/python-best-way-to-create-directory-if-it-doesnt-exist-for-file-write.
        """
        try:
            os.makedirs(path)
        except OSError, exception:
            if exception.errno != errno.EEXIST:
                raise

    def remove_directory(self):
        """Remove the directory of the FomaFST instance.

        :returns: an absolute path to the directory for the phonology.

        """
        try:
            rmtree(self.directory)
        except Exception:
            return None

    def esc_RE_meta_chars(self, string):
        """Escapes regex metacharacters in ``string``.

            >>> esc_RE_meta_chars(u'-')
            u'\\\-'

        """
        def esc(c):
            if c in u'\\^$*+?{,}.|][()^-':
                return re.escape(c)
            return c
        return ''.join([esc(c) for c in string])

    @property
    def morpheme_splitter(self):
        """Return a function that will split words into morphemes and delimiters."""
        try:
            return self._morpheme_splitter
        except AttributeError:
            delimiters = self.delimiters
            self._morpheme_splitter = lambda x: [x] # default, word is morpheme
            if delimiters:
                self._morpheme_splitter = re.compile(u'([%s])' %
                    ''.join([self.esc_RE_meta_chars(d) for d in delimiters])).split
            return self._morpheme_splitter

    @property
    def morpheme_only_splitter(self):
        """Return a function that will split words into morphemes, excluding delimiters."""
        try:
            return self._morpheme_only_splitter
        except AttributeError:
            delimiters = self.delimiters
            self._morpheme_splitter = lambda x: [x] # default, word is morpheme
            if delimiters:
                self._morpheme_splitter = re.compile(u'[%s]' %
                    ''.join([self.esc_RE_meta_chars(d) for d in delimiters])).split
            return self._morpheme_splitter

    @property
    def delimiters(self):
        """Return a list of morpheme delimiters.

        Note: we generate the list ``self._delimiters`` from the unicode object ``self.morpheme_delimiters``
        if the latter exists; the rationale for this is that SQLAlchemy-based FSTs cannot persist Python
        lists so the ``morpheme_delimiters`` attribute stores the string representing the list.

        """

        try:
            return self._delimiters
        except AttributeError:
            morpheme_delimiters = getattr(self, 'morpheme_delimiters', None)
            if morpheme_delimiters:
                self._delimiters = morpheme_delimiters.split(u',')
            else:
                self._delimiters = []
            return self._delimiters

    def run(self, cmd, timeout):
        """Run :func:`cmd` as a subprocess that is terminated within ``timeout`` seconds.

        :param list cmd: the command-line command as represeted as a list of strings.
        :param float timeout: time in seconds by which :func:`self.cmd` will be terminated.
        :return: 2-tuple: return code of process, stdout

        """
        def target():
            with open(self.logpath or os.devnull, "w") as logfile:
                self.process = Popen(cmd, stdout=logfile, stderr=logfile)
            self.process.communicate()
        thread = threading.Thread(target=target)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.kill_process(self.process)
            thread.join()
        try:
            stdout = open(self.logpath).read()
        except Exception:
            stdout = ''
        return self.process.returncode, stdout

    def kill_process(self, process):
        """Kill ``process`` and all its child processes."""
        pid = process.pid
        pids = [pid]
        pids.extend(self.get_process_children(pid))
        for pid in pids:
            try: 
                os.kill(pid, SIGKILL)
            except OSError:
                pass

    def get_process_children(self, pid):
        """Return list of pids of child processes of ``pid``."""
        p = Popen('ps --no-headers -o pid --ppid %d' % pid, shell=True,
                  stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        return [int(p) for p in stdout.split()]

    def executable_installed(self, name):
        """Check if executable ``name`` is in the user's PATH."""
        for path in os.environ['PATH'].split(os.pathsep):
            path = path.strip('"')
            program_path = os.path.join(path, name)
            if os.path.isfile(program_path) and os.access(program_path, os.X_OK):
                return True
        return False

    def get_modification_time(self, path):
        """Return the modification time of the file or directory with ``path``."""
        try:
            return os.path.getmtime(path)
        except Exception:
            return None

    def copy_files(self, dst):
        """Copy all files in ``self.directory`` to ``dst``.
        """
        directory = self.directory
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                copyfile(path, os.path.join(dst, name))

class FomaFST(Command):
    """Represents a foma finite-state transducer.

    The FomaFST class is Python logic wrapping foma/flookup functionality;
    Really, this is just a very restricted interface to subprocess.Popen(['foma', ...]).

    This class is designed to be both a superclass to an OLD SQLAlchemy-based model (e.g.,
    a phonology, morphology or morphophonology) as well as a factory for stand-alone foma-based
    objects.  The three main "public" methods are ``save_script``, ``compile``, ``apply`` (and
    its conveniences, ``applyup`` and ``applydown``).

    Usage:

        import time
        from onlinelinguisticdatabase.lib.parser import FomaFST
        parent_directory = '/home/dave/phonology'
        phonology = FomaFST(parent_directory, u'#', u'phonology')
        phonology.script = u'define phonology a -> b || c _ d;'
        phonology.save_script()
        compile_attempt = phonology.compile_attempt
        phonology.compile()
        while phonology.compile_attempt == compile_attempt: time.sleep(2)
        print phonology.applyup(u'cbd')                 # {u'cbd': [u'cbd', u'cad']
        print phonology.applydown(u'cad')               # {u'cad': [u'cbd']}
        print phonology.applyup([u'cbd', u'dog'])       # {u'cbd': [u'cbd', u'cad'], u'dog': [u'dog']}
        print phonology.applyup([u'cad', u'dog'])       # {u'cad': [u'cbd'], u'dog': [u'dog']}

    """

    def __init__(self, parent_directory, **kwargs):
        self.compile_attempt = None
        self.word_boundary_symbol = kwargs.pop('word_boundary_symbol', self.default_word_boundary_symbol)
        kwargs['object_type'] = kwargs.get('object_type', u'foma_fst')
        super(FomaFST, self).__init__(parent_directory, **kwargs)

    @property
    def file_type2extension(self):
        """Extend the base class's property of the same name so that ``get_file_path``
        works appropriately for this type of command."""
        if getattr(self, '_file_type2extension', None):
            return self._file_type2extension
        else:
            self._file_type2extension = super(FomaFST, self).file_type2extension.copy()
            self._file_type2extension.update({
                'script': '.script',
                'binary': '.foma',
                'compiler': '.sh'
            })
            return self._file_type2extension

    def generate_salt(self):
        return unicode(uuid4().hex)

    def applyup(self, input_, boundaries=None):
        return self.apply('up', input_)

    def applydown(self, input_, boundaries=None):
        return self.apply('down', input_)

    def apply(self, direction, input_, boundaries=None):
        """Foma-apply the inputs in the direction of ``direction``.

        The method used is to write two files -- inputs.txt containing a newline-delimited
        list thereof and apply.sh which is a shell script that invokes flookup on inputs.txt
        to create outputs.txt -- and then parse the foma/flookup-generated outputs.txt file
        and then delete the three temporary files.  A more efficient implementation might be
        possible.

        :param str direction: 'up' or 'down', i.e., the direction in which to use the transducer
        :param basestring/list input_: a transcription string or list thereof.
        :param bool boundaries: whether or not to add word boundary symbols to the inputs and remove
            them from the outputs.
        :returns: a dictionary: ``{input1: [output1, output2, ...], input2: [...], ...}``

        """
        boundaries = boundaries if boundaries is not None else getattr(self, 'boundaries', False)
        if isinstance(input_, basestring):
            inputs = [input_]
        elif isinstance(input_, (list, tuple)):
            inputs = list(input_)
        else:
            return None
        directory = self.directory
        random_string = self.generate_salt()
        inputs_file_path = os.path.join(directory, 'inputs_%s.txt' % random_string)
        outputs_file_path = os.path.join(directory, 'outputs_%s.txt' % random_string)
        apply_file_path = os.path.join(directory, 'apply_%s.sh' % random_string)
        binary_path = self.get_file_path('binary')
        # Write the inputs to an '\n'-delimited file
        with codecs.open(inputs_file_path, 'w', 'utf8') as f:
            if boundaries:
                f.write(u'\n'.join(input_.join([self.word_boundary_symbol, self.word_boundary_symbol])
                        for input_ in inputs))
            else:
                f.write(u'\n'.join(inputs))
        # Write the shell script that pipes the input file into flookup
        with codecs.open(apply_file_path, 'w', 'utf8') as f:
            f.write('#!/bin/sh\ncat %s | flookup %s%s' % (
                inputs_file_path,
                {'up': '', 'down': '-i '}.get(direction, '-i '),
                binary_path))
        os.chmod(apply_file_path, 0744)
        # Execute the shell script and pipe its output to the output file
        with open(os.devnull, 'w') as devnull:
            with codecs.open(outputs_file_path, 'w', 'utf8') as outfile:
                p = Popen(apply_file_path, shell=False, stdout=outfile, stderr=devnull)
        p.communicate()
        # Parse the output file, clean up and return the parsed outputs
        with codecs.open(outputs_file_path, 'r', 'utf8') as f:
            result = self.foma_output_file2dict(f, remove_word_boundaries=boundaries)
        os.remove(inputs_file_path)
        os.remove(outputs_file_path)
        os.remove(apply_file_path)
        return result

    def foma_output_file2dict(self, file_, remove_word_boundaries=True):
        """Return the output file of a flookup apply request into a dictionary.

        :param file file_: utf8-encoded file object with tab-delimited i/o pairs.
        :param bool remove_word_boundaries: toggles whether word boundaries are removed in the output
        :returns: dictionary of the form ``{i1: [01, 02, ...], i2: [...], ...}``.

        .. note::

            The flookup foma utility returns '+?' when there is no output for a given 
            input -- hence the replacement of '+?' with None below.

        """
        def word_boundary_remover(x):
            if (x[0:1], x[-1:]) == (self.word_boundary_symbol, self.word_boundary_symbol):
                return x[1:-1]
            else:
                return x
        remover = word_boundary_remover if remove_word_boundaries else (lambda x: x)
        result = {}
        for line in file_:
            line = line.strip()
            if line:
                i, o = map(remover, line.split('\t')[:2])
                result.setdefault(i, []).append({self.flookup_no_output: None}.get(o, o))
        return dict((k, filter(None, v)) for k, v in result.iteritems())

    # Cf. http://code.google.com/p/foma/wiki/RegularExpressionReference#Reserved_symbols
    foma_reserved_symbols = [u'\u0021', u'\u0022', u'\u0023', u'\u0024', u'\u0025',
        u'\u0026', u'\u0028', u'\u0029', u'\u002A', u'\u002B', u'\u002C', u'\u002D',
        u'\u002E', u'\u002F', u'\u0030', u'\u003A', u'\u003B', u'\u003C', u'\u003E',
        u'\u003F', u'\u005B', u'\u005C', u'\u005D', u'\u005E', u'\u005F', u'\u0060',
        u'\u007B', u'\u007C', u'\u007D', u'\u007E', u'\u00AC', u'\u00B9', u'\u00D7',
        u'\u03A3', u'\u03B5', u'\u207B', u'\u2081', u'\u2082', u'\u2192', u'\u2194',
        u'\u2200', u'\u2203', u'\u2205', u'\u2208', u'\u2218', u'\u2225', u'\u2227',
        u'\u2228', u'\u2229', u'\u222A', u'\u2264', u'\u2265', u'\u227A', u'\u227B']

    # This is the string that flookup returns when an input has no output.
    flookup_no_output = u'+?'

    default_word_boundary_symbol = u'#'

    foma_reserved_symbols_patt = re.compile(u'[%s]' % u''.join(foma_reserved_symbols))

    def escape_foma_reserved_symbols(self, string):
        """Prepend foma reserved symbols with % to escape them."""
        return self.foma_reserved_symbols_patt.sub(lambda m: u'%' + m.group(0), string)

    def delete_foma_reserved_symbols(self, string):
        """Delete foma reserved symbols -- good for names of defined regexes."""
        return self.foma_reserved_symbols_patt.sub(u'', string)

    def compile(self, timeout=30*60, verification_string=None):
        """Compile the foma FST's script.

        The superclass's ``run`` method performs the compilation request and cancels it if
        it exceeds ``timeout`` seconds.

        :param float/int timeout: how long to wait before terminating the compile process.
        :param str verification_string]: a string that will be found in the stdout of a successful foma request.
        :returns: ``None``.  Attribute values of the Foma FST object are altered to reflect the success
            (or not) of the compilation.  If successful, ``self.get_file_path('binary')`` will be return
            the absolute path to the compiled foma FST.

        """
        verification_string = verification_string or self.verification_string
        compiler_path = self.get_file_path('compiler')
        binary_path = self.get_file_path('binary')
        binary_mod_time = self.get_modification_time(binary_path)
        self.compile_succeeded = False
        try:
            returncode, output = self.run([compiler_path], timeout)
            if verification_string in output:
                if returncode == 0:
                    if (os.path.isfile(binary_path) and
                        binary_mod_time != self.get_modification_time(binary_path)):
                        self.compile_succeeded = True
                        self.compile_message = (u'Compilation process terminated '
                            'successfully and new binary file was written.')
                    else:
                        self.compile_message = (u'Compilation process terminated '
                            'successfully yet no new binary file was written.')
                else:
                    self.compile_message = u'Compilation process failed.'
            else:
                self.compile_message = u'Foma script is not a well-formed %s.' % self.object_type
        except Exception:
            self.compile_message = u'Compilation attempt raised an error.'
        if self.compile_succeeded:
            os.chmod(binary_path, 0744)
        else:
            try:
                os.remove(binary_path)
            except Exception:
                pass
        self.compile_attempt = unicode(uuid4())

    def save_script(self):
        """Save the unicode value of ``self.script`` to disk.

        Also create the compiler shell script which will be used to compile the script.

        :returns: the absolute path to the newly created foma FST script file.

        """
        try:
            self.make_directory_safely(self.directory)
            script_path = self.get_file_path('script')
            binary_path = self.get_file_path('binary')
            compiler_path = self.get_file_path('compiler')
            with codecs.open(script_path, 'w', 'utf8') as f:
                f.write(self.script)
            # The compiler shell script loads the foma script and compiles it to binary form.
            with open(compiler_path, 'w') as f:
                f.write('#!/bin/sh\nfoma -e "source %s" -e "regex %s;" '
                        '-e "save stack %s" -e "quit"' % (
                        script_path, self.object_type, binary_path))
            os.chmod(compiler_path, 0744)
            return script_path
        except Exception:
            return None

    def get_tests(self):
        """Return as a dictionary any tests defined in the script.

        By convention established here, a line in a foma script that begins with
        "#test " signifies a test.  After "#test " there should be a string of
        characters followed by "->" followed by another string of characters.  The
        first string is the lower side of the tape and the second is the upper side. 

        """

        try:
            result = {}
            test_lines = [l[6:] for l in self.script.splitlines() if l[:6] == u'#test ']
            for l in test_lines:
                try:
                    i, o = map(unicode.strip, l.split(u'->'))
                    result.setdefault(i, []).append(o)
                except ValueError:
                    pass
            return result
        except Exception:
            return None

    def run_tests(self):
        """Run all tests defined in the script and return a report.

        :returns: a dictionary representing the report on the tests.

        A line in a script that begins with "#test " signifies a
        test.  After "#test " there should be a string of characters followed by
        "->" followed by another string of characters.  The first string is the
        lower side of the tape and the second is the upper side. 

        """

        tests = self.get_tests()
        if not tests:
            return None
        results = self.applydown(tests.keys())
        return dict([(t, {'expected': tests[t], 'actual': results[t]}) for t in tests])


class PhonologyFST(FomaFST):
    """Represents a foma-based phonology finite-state transducer.
    """

    def __init__(self, parent_directory, **kwargs):
        kwargs['object_type'] = kwargs.get('object_type', u'phonology')
        super(PhonologyFST, self).__init__(parent_directory, **kwargs)

    boundaries = True


class MorphologyFST(FomaFST):
    """Represents a foma-based morphology finite-state transducer.
    """

    def __init__(self, parent_directory, **kwargs):
        self.rare_delimiter = kwargs.pop('rare_delimiter', u'\u2980')
        kwargs['object_type'] = kwargs.get('object_type', u'morphology')
        super(MorphologyFST, self).__init__(parent_directory, **kwargs)

    @property
    def verification_string(self):
        """The verification string of a morphology varies depending on whether the script
        is written using the lexc formalism or the regular expression one.
        """
        if getattr(self, '_verification_string', None):
            return self._verification_string
        if getattr(self, 'script_type', None) == 'lexc':
            self._verification_string =  u'Done!'
        else:
            self._verification_string =  u'defined %s: ' % self.object_type
        return self._verification_string

    @property
    def file_type2extension(self):
        if getattr(self, '_file_type2extension', None):
            return self._file_type2extension
        else:
            self._file_type2extension = super(MorphologyFST, self).file_type2extension.copy()
            self._file_type2extension.update({
                'lexicon': '.pickle',
                'dictionary': '_dictionary.pickle',
            })
            return self._file_type2extension


class LanguageModel(Command):
    """Represents ngram language model objects.

    This class assumes that the elements of the model are morphemes, not words.
    Basically an interface to an LM toolkit that is mediated by Python subprocess control.

    Primary read methods are ``get_probabilities`` and ``get_probability_one``.  Primary
    write methods are ``write_arpa`` and ``generate_trie``, which should be called in that
    order and which assume appropriate values for ``self.n`` and ``self.smoothing`` as well
    as a corpus (and possibly a vocabulary) file written at ``self.get_file_path('corpus')``
    (and at ``self.get_file_path('vocabulary')``).

    .. note::

        At present, only support for the MITLM toolkit is implemented.

    """

    def __init__(self, parent_directory, **kwargs):
        self.rare_delimiter = kwargs.pop('rare_delimiter', u'\u2980')
        self.start_symbol = kwargs.pop('start_symbol', u'<s>')
        self.end_symbol = kwargs.pop('end_symbol', u'</s>')
        kwargs['object_type'] = kwargs.get('object_type', u'morpheme_language_model')
        super(LanguageModel, self).__init__(parent_directory, **kwargs)

    toolkits = {
        'mitlm': {
            'executable': 'estimate-ngram',
            'smoothing_algorithms': [
                # cf. http://code.google.com/p/mitlm/wiki/Tutorial
                'ML', 'FixKN', 'FixModKN', 'FixKNn', 'KN', 'ModKN', 'KNn'], 
            'verification_string_getter': lambda x: u'Saving LM to %s' % x
        }
    }

    object_type2directory_name = {'morphemelanguagemodel': 'morpheme_language_model'}
    object_type2file_name = {'morphemelanguagemodel': 'morpheme_language_model'}

    @property
    def verification_string(self):
        return self.toolkits[self.toolkit]['verification_string_getter'](
            self.get_file_path('arpa'))

    @property
    def executable(self):
        return self.toolkits[self.toolkit]['executable']

    @property
    def file_type2extension(self):
        if getattr(self, '_file_type2extension', None):
            return self._file_type2extension
        else:
            self._file_type2extension = super(LanguageModel, self).file_type2extension.copy()
            self._file_type2extension.update({
                'corpus': '.txt',
                'arpa': '.lm',
                'trie': '.pickle',
                'vocabulary': '.vocab'
            })
            return self._file_type2extension

    space_splitter = re.compile('\s+')

    def get_probabilities(self, input_):
        """Return the probability of each sequence of morphemes in ``input_``.

        :param basestring/list input_: a string of space-delimited morphemes or a list thereof.
            Word boundary symbols will be added automatically and should not be included.
        :returns: a dictionary with morpheme sequences as keys and log probabilities as values.

        """
        if isinstance(input_, basestring):
            morpheme_sequences = [input_]
        elif isinstance(input_, (list, tuple)):
            morpheme_sequences = input_
        else:
            return None
        splitter = self.space_splitter
        morpheme_sequences = [(morpheme_sequence,
            [self.start_symbol] + splitter.split(morpheme_sequence) + [self.end_symbol])
            for morpheme_sequence in morpheme_sequences]
        trie = self.trie
        return dict((morpheme_sequence, self.get_probability_one(morpheme_sequence_list, trie))
                    for morpheme_sequence, morpheme_sequence_list in morpheme_sequences)

    def get_probability_one(self, morpheme_sequence_list, trie=None):
        """Return the log probability of the input list of morphemes.

        :param list morpheme_sequence_list: a list of strings/unicode obejcts, each
            representing a morpheme.
        :param instance trie: a simplelm.LMTree instance encoding the LM.
        :returns: the log prob of the morpheme sequence.

        """
        if not trie:
            trie = self.trie
        return simplelm.compute_sentence_prob(trie, morpheme_sequence_list)

    def write_arpa(self, timeout):
        """Write ARPA-formatted LM file to disk.

        :param int/float timeout: how many seconds to wait before canceling the write attempt.
        :returns: None; an exception is raised if ARPA file generation fails.

        .. note::

            This method assumes that the attributes ``order`` and ``smoothing`` are
            defined and that appropriate corpus (and possibly vocabulary) files have
            been written.

        """

        verification_string = self.verification_string
        arpa_path = self.get_file_path('arpa')
        arpa_mod_time = self.get_modification_time(arpa_path)
        cmd = self.write_arpa_command
        returncode, output = self.run(cmd, timeout)
        succeeded = (verification_string in output and
                     returncode == 0 and
                     os.path.isfile(arpa_path) and
                     arpa_mod_time != self.get_modification_time(arpa_path))
        if not succeeded:
            raise Exception('method write_arpa failed.')

    @property
    def write_arpa_command(self):
        """Returns a list of strings representing a command to generate an ARPA file using the toolkit."""
        cmd = []
        if self.toolkit == u'mitlm':
            order = str(self.order)
            smoothing = self.smoothing or 'ModKN'
            cmd = [self.executable, '-o', order, '-s', smoothing,
                   '-t', self.get_file_path('corpus'), '-wl', self.get_file_path('arpa')]
            if self.vocabulary:
                cmd += ['-v', self.get_file_path('vocabulary')]
        return cmd

    @property
    def vocabulary(self):
        """Return ``True`` if we have a vocabulary file."""
        if os.path.isfile(self.get_file_path('vocabulary')):
            return True
        return False

    def generate_trie(self):
        """Load the contents of an ARPA-formatted LM file into a ``simplelm.LMTree`` instance and pickle it.

        :returns: None; if successful, ``self.get_file_path('trie')`` points to a pickled
            ``simplelm.LMTree`` instance.

        """
        self._trie = simplelm.load_arpa(self.get_file_path('arpa'), 'utf8')
        cPickle.dump(self._trie, open(self.get_file_path('trie'), 'wb'))

    @property
    def trie(self):
        """Return the ``simplelm.LMTree`` instance representing a trie interface to the LM
        if one is available or can be generated.

        """
        if isinstance(getattr(self, '_trie', None), simplelm.LMTree):
            return self._trie
        else:
            try:
                self._trie = cPickle.load(open(self.get_file_path('trie'), 'rb'))
                return self._trie
            except Exception:
                try:
                    self.generate_trie()
                    return self._trie
                except Exception:
                    return None


class Cache(object):
    """For caching parses; basically a dict with some conveniences and pickle-based persistence.

    A MorphologicalParser instance can be expected to access and set keys via the familiar Python
    dictionary interface as well as request that the cache be persisted, i.e., by calling
    ``cache.persist()``.  Thus this class implements the following interface:

    - ``__setitem__(k, v)``
    - ``__getitem__(k)``
    - ``get(k, default)``
    - ``persist()``

    """

    def __init__(self, path=None):
        self.updated = False # means that ``self._store`` is in sync with persistent cache
        self.path = path # without a path, pickle-based persistence is impossible
        self._store = {}
        if self.path and os.path.isfile(self.path):
            try:
                self._store = cPickle.load(open(self.path, 'rb'))
                if not isinstance(self._store, dict):
                    self._store = {}
            except Exception:
                pass

    def __setitem__(self, k, v):
        if k not in self._store:
            self.updated = True
        self._store[k] = v

    def __getitem__(self, k):
        return self._store[k]

    def get(self, k, default=None):
        return self._store.get(k, default)

    def update(self, dict_, **kwargs):
        old_keys = self._store.keys()
        self._store.update(dict_, **kwargs)
        if set(old_keys) != set(self._store.keys()):
            self.updated = True

    def persist(self):
        """Update the persistence layer with the value of ``self._store``.
        """
        if self.updated and self.path:
            cPickle.dump(self._store, open(self.path, 'wb'))
            self.updated = False

    def clear(self, persist=False):
        """Clear the cache and its persistence layer.
        """
        self._store = {}
        if persist:
            self.updated = True
            self.persist()


class MorphologicalParser(FomaFST):
    """Represents a morphological parser: a morphophonology FST filtered by an ngram LM.

    The primary read methods are ``parse`` and ``parse_one``.  In order to function correctly,
    a MorphologicalParser instance must have ``morphology``, ``phonology`` and ``language_model``
    attributes whose values are fully generated and compiled ``Morphology``, ``Phonology`` and
    ``LanguageModel`` instances, respectively.

    """

    def __init__(self, parent_directory, **kwargs):
        kwargs['object_type'] = kwargs.get('object_type', u'morphologicalparser')
        self.cache = kwargs.pop('cache', Cache())
        self.persist_cache = kwargs.pop('persist_cache', True)
        super(MorphologicalParser, self).__init__(parent_directory, **kwargs)

    boundaries = True # parsers transparently/automatically wrap input transcriptions in word boundary symbols
    object_type2directory_name = {'morphologicalparser': 'morphological_parser'}
    object_type2file_name = {'morphologicalparser': 'morphophonology'}

    @property
    def cache(self):
        if getattr(self, '_cache', None):
            return self._cache
        else:
            self._cache = Cache()
            return self._cache

    @cache.setter
    def cache(self, value):
        self._cache = value

    @property
    def verification_string(self):
        return u'defined %s: ' % self.object_type2file_name.get(
            self.object_type, self.object_type)

    def pretty_parse(self, input_,):
        result = self.parse(input_)
        result = dict((k, self.parse2triplet(v)) for k, v in result.iteritems())
        return result

    def parse2triplet(self, parse):
        """Convert a string representing a sequence of morphemes to a list of three strings,
        i.e., forms, glosses, categories.  To illustrate, if ``parse`` is 'chien|dog|N-s|PL|Phi',
        output will be ['chien-s', 'dog-PL', 'N-Phi'].

        """

        if not parse:
            return parse
        triplet = []
        for index, item in enumerate(self.morpheme_splitter(parse)):
            if index % 2 == 0:
                triplet.append(item.split(self.my_morphology.rare_delimiter))
            else:
                triplet.append([item, item, item])
        return [u''.join(item) for item in zip(*triplet)]

    def parse(self, input_):
        """Parse the input(s) and return a dictionary from inputs to parses

        :param basestring/list input_: a transcription of a word or a list thereof.
        :returns: a dictionary with input transcriptions as keys and parses as values.

        """
        if isinstance(input_, basestring):
            result = {input_: self.parse_one(input_)}
        else:
            result = dict((t, self.parse_one(t)) for t in input_)
        if self.persist_cache:
            self.cache.persist()
        return result

    def parse_one(self, transcription):
        """Return the most probable parse for the input transcription.

        :param unicode transcription: a surface form of a word.
        :returns: unicode object representing the most probable parse of the transcription.

        """
        parse = self.cache.get(transcription, False)
        if parse is False:
            candidates = self.get_candidates(transcription)
            parse = self.get_most_probable(candidates)
            self.cache[transcription] = parse
        return parse

    def get_most_probable(self, candidates):
        """Uses ``self.my_language_model`` to return the most probable of a list of candidate parses.

        :param list candidates: list of unicode strings representing morphological parses.
            These must be in 'f|g|c-f|g|c' format, i.e., morphemes are ``self.rare_delimiter``-
            delimited form/gloss/category triples delimited by morpheme delimiters.
        :returns: the most probable candidate in candidates.

        """
        if not candidates:
            return None
        temp = []
        for candidate in candidates:
            lm_input = self.morpheme_splitter(candidate)[::2]
            if self.my_language_model.categorial:
                lm_input = [morpheme.split(self.my_morphology.rare_delimiter)[2]
                    for morpheme in lm_input]
            lm_input = ([self.my_language_model.start_symbol] + lm_input +
                        [self.my_language_model.end_symbol])
            temp.append((candidate, self.my_language_model.get_probability_one(lm_input)))
        return sorted(temp, key=lambda x: x[1])[-1][0]

    def get_candidates(self, transcription):
        """Returns the morphophonologically valid parses of the input transcription.

        :param unicode transcription: a surface transcription of a word.
        :returns: a list of strings representing candidate parses in 'form|gloss|category' format.

        """

        candidate_parses = self.applyup(transcription)[transcription]
        if not self.my_morphology.rich_morphemes:
            candidate_parses = self.disambiguate(candidate_parses)
        return candidate_parses

    def disambiguate(self, candidates):
        """Return parse candidates with rich representations, i.e., disambiguated.

        Note that this is only necessary when ``self.my_morphology.rich_morphemes==False``.

        :param list candidates: a list of strings representing morphological parses.  Since
            they are being disambiguated, we should expect them to be morpheme forms
            delimited by the language's delimiters.
        :returns: a list of richly represented morphological parses, i.e., in f|g|c format.

        This converts something like 'chien-s' to 'chien|dog|N-s|PL|Phi'.

        """

        def get_category(morpheme):
            if type(morpheme) == list:
                return morpheme[2]
            return morpheme
        def get_morpheme(morpheme):
            if type(morpheme) == list:
                return self.my_morphology.rare_delimiter.join(morpheme)
            return morpheme
        rules = self.my_morphology.rules_generated.split()
        dictionary_path = self.my_morphology.get_file_path('dictionary')
        try:
            dictionary = cPickle.load(open(dictionary_path, 'rb'))
            new_candidates = set()
            for candidate in candidates:
                temp = []
                morphemes = self.morpheme_splitter(candidate)
                for index, morpheme in enumerate(morphemes):
                    if index % 2 == 0:
                        homographs = [[morpheme, gloss, category]
                                for gloss, category in dictionary[morpheme]]
                        temp.append(homographs)
                    else:
                        temp.append(morpheme) # it's really a delimiter
                for candidate in product(*temp):
                    # Only add a disambiguated candidate if its category sequence accords with the morphology's rules
                    if ''.join(get_category(x) for x in candidate) in rules:
                        new_candidates.add(u''.join(get_morpheme(x) for x in candidate))
            return list(new_candidates)
        except Exception, e:
            log.warn('some kind of exception occured in morphologicalparsers.py '
                    'disambiguate_candidates: %s' % e)
            return []

    # A parser's morphology and language_model objects should always be accessed via the
    # ``my_``-prefixed properties defined below.  These properties abstract away the complication
    # that ``self.my_X`` may be a copy of ``self.X``.  The rationale behind this is that in a
    # multi-user, multithreaded environment the updating of a referenced object (e.g., LM) should
    # not silently change the behaviour of a parser -- the parser must be explicitly rewritten and re-compiled
    # in order for changes to percolate.  This level of abstraction is important in the context
    # of parse caching: if changes to, say, a referenced LM object were to silently change the
    # parses of a parser, the parser's cache would not be cleared and those changes would not
    # surface in parsing behaviour.

    @property
    def my_morphology(self):
        try:
            return self._my_morphology
        except AttributeError:
            self._my_morphology = self.morphology
            return self._my_morphology

    @my_morphology.setter
    def my_morphology(self, value):
        self._my_morphology = value

    @property
    def my_language_model(self):
        try:
            return self._my_language_model
        except AttributeError:
            self._my_language_model = self.language_model
            return self._my_language_model

    @my_language_model.setter
    def my_language_model(self, value):
        self._my_language_model = value

    def export(self):
        """Return a dictionary containing all of the core attribute/values of the parser.
        """

        return {
            'phonology': {
                'word_boundary_symbol': getattr(self.phonology, 'word_boundary_symbol', u'#')
            },
            'morphology': {
                'word_boundary_symbol': getattr(self.my_morphology, 'word_boundary_symbol', u'#'),
                'rare_delimiter': getattr(self.my_morphology, 'rare_delimiter', u'\u2980'),
                'rich_morphemes': getattr(self.my_morphology, 'rich_morphemes', True),
                'rules_generated': getattr(self.my_morphology, 'rules_generated', u'')
            },
            'language_model': {
                'rare_delimiter': getattr(self.my_language_model, 'rare_delimiter', u'\u2980'),
                'start_symbol': getattr(self.my_language_model, 'start_symbol', u'<s>'),
                'end_symbol': getattr(self.my_language_model, 'end_symbol', u'</s>'),
                'categorial': getattr(self.my_language_model, 'categorial', False)
            },
            'parser': {
                'word_boundary_symbol': getattr(self, 'word_boundary_symbol', u'#'),
                'morpheme_delimiters': getattr(self, 'morpheme_delimiters', None)
            }
        }

    @property
    def file_type2extension(self):
        """Extend the base class's property of the same name so that ``get_file_path``
        works appropriately for this type of command."""
        if getattr(self, '_file_type2extension', None):
            return self._file_type2extension
        else:
            self._file_type2extension = super(MorphologicalParser, self).file_type2extension.copy()
            self._file_type2extension.update({'cache': '_cache.pickle'})
            return self._file_type2extension
